"""Unit tests for LightRAGClient (plan.md Phase 4.2 subset relevant to
client.py -- get_pipeline_status's 30KB->2KB summarization is a Phase 3
tool concern and is tested there instead).

Every test builds a LightRAGClient with an httpx2.MockTransport instead of
a real network transport, per plan.md's verified approach: respx does not
work with httpx2, but passing a handler function straight into
httpx2.AsyncClient(transport=...) does.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2 as httpx
import pytest

from mcp_lightrag.client import LightRAGClient
from mcp_lightrag.errors import LightRAGConnectionError, LightRAGError

BASE_URL = "http://lightrag.test"


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> LightRAGClient:
    return LightRAGClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        **kwargs,  # type: ignore[arg-type]
    )


# --- auth headers -----------------------------------------------------


async def test_sends_api_key_header_when_configured() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, api_key="secret-key")
    result = await client.request("GET", "/health")

    assert result == {"ok": True}
    assert seen["x-api-key"] == "secret-key"
    assert "authorization" not in seen


async def test_no_api_key_header_when_not_configured() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    await client.request("GET", "/health")

    assert "x-api-key" not in seen
    assert "authorization" not in seen


# --- non-2xx -> LightRAGError ------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "body_kwargs", "expected_detail"),
    [
        (
            403,
            {"json": {"detail": "API Key required or incorrect API Key"}},
            "API Key required or incorrect API Key",
        ),
        (404, {"json": {"detail": "Not Found"}}, "Not Found"),
        (405, {"text": "Method Not Allowed"}, "Method Not Allowed"),
        (
            422,
            {"json": {"detail": [{"msg": "field required"}]}},
            "[{'msg': 'field required'}]",
        ),
        (500, {"text": "Internal Server Error"}, "Internal Server Error"),
    ],
)
async def test_non_2xx_becomes_lightrag_error(
    status_code: int, body_kwargs: dict[str, object], expected_detail: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, **body_kwargs)  # type: ignore[arg-type]

    client = make_client(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await client.request("GET", "/documents/status_counts")

    err = exc_info.value
    assert err.status_code == status_code
    assert err.method == "GET"
    assert err.path == "/documents/status_counts"
    assert err.detail == expected_detail
    assert (
        str(err)
        == f"LightRAG {status_code} on GET /documents/status_counts: {expected_detail}"
    )


async def test_401_without_credentials_becomes_lightrag_error() -> None:
    """A 401 with no username/password configured is just an error -- the
    login-and-retry path only engages when credentials are set.
    """

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"detail": "Not authenticated"})

    client = make_client(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await client.request("GET", "/documents/status_counts")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Not authenticated"
    assert calls == 1


# --- timeout / connection failure -> LightRAGConnectionError -----------


async def test_timeout_becomes_lightrag_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = make_client(handler)

    with pytest.raises(LightRAGConnectionError) as exc_info:
        await client.request("POST", "/query")

    assert exc_info.value.base_url == BASE_URL
    assert exc_info.value.reason == "timed out"
    assert str(exc_info.value) == f"LightRAG unreachable at {BASE_URL} (timed out)"


async def test_get_retries_once_on_connect_error_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    result = await client.request("GET", "/health")

    assert result == {"ok": True}
    assert calls == 2


async def test_get_connection_error_after_retry_raises() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)

    with pytest.raises(LightRAGConnectionError):
        await client.request("GET", "/health")

    assert calls == 2  # one try + one retry, never more


async def test_post_does_not_retry_on_connect_error() -> None:
    """POST/DELETE must never auto-retry: retrying a request with side
    effects risks inserting or deleting data twice.
    """

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)

    with pytest.raises(LightRAGConnectionError):
        await client.request("POST", "/documents/text")

    assert calls == 1


# --- JWT login flow -----------------------------------------------------


async def test_login_sends_form_body_and_stores_jwt() -> None:
    login_calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            login_calls.append(request.content)
            return httpx.Response(200, json={"access_token": "jwt-abc"})
        assert request.headers.get("authorization") == "Bearer jwt-abc"
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, username="alice", password="hunter2")
    await client._login()

    assert len(login_calls) == 1
    body = login_calls[0].decode()
    assert "username=alice" in body
    assert "password=hunter2" in body

    result = await client.request("GET", "/health")
    assert result == {"ok": True}


async def test_401_triggers_login_and_retry_when_credentials_configured() -> None:
    state = {"logged_in": False}
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        if request.url.path == "/login":
            state["logged_in"] = True
            return httpx.Response(200, json={"access_token": "fresh-jwt"})

        request_count += 1
        if not state["logged_in"]:
            return httpx.Response(401, json={"detail": "token expired"})
        assert request.headers.get("authorization") == "Bearer fresh-jwt"
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, username="alice", password="hunter2")
    result = await client.request("GET", "/documents/status_counts")

    assert result == {"ok": True}
    assert request_count == 2  # first 401, then the retry that succeeds


async def test_401_after_login_retry_still_raises() -> None:
    """If the retried request still 401s (e.g. bad credentials), the
    second failure must surface as a normal LightRAGError, not loop forever.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(200, json={"access_token": "jwt-xyz"})
        return httpx.Response(401, json={"detail": "Invalid token"})

    client = make_client(handler, username="alice", password="wrong")

    with pytest.raises(LightRAGError) as exc_info:
        await client.request("GET", "/documents/status_counts")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


# --- empty response body -------------------------------------------------


async def test_empty_response_body_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    client = make_client(handler)
    result = await client.request("DELETE", "/documents")

    assert result is None
