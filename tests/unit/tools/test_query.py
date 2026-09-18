"""Unit tests for tools/query.py (`query`, `query_data`)."""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGConnectionError, LightRAGError
from mcp_lightrag.tools.query import query, query_data
from tests.unit.conftest import make_ctx


async def test_query_success_sends_defaults_and_returns_response() -> None:
    seen_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "response": "The answer.",
                "references": [{"reference_id": "1", "file_path": "a.md"}],
            },
        )

    ctx, _client = make_ctx(handler)
    result = await query(ctx, query="What does JOC do?")

    assert result["response"] == "The answer."
    assert result["references"][0]["file_path"] == "a.md"
    assert seen_payload["query"] == "What does JOC do?"
    assert seen_payload["mode"] == "mix"
    assert seen_payload["include_references"] is True
    # Optional fields left at their default (None) must not be sent at all.
    assert "top_k" not in seen_payload
    assert "user_prompt" not in seen_payload


async def test_query_forwards_optional_params_when_given() -> None:
    seen_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "ok"})

    ctx, _client = make_ctx(handler)
    await query(
        ctx,
        query="hi",
        mode="local",
        top_k=10,
        response_type="Bullet Points",
        include_references=False,
    )

    assert seen_payload["mode"] == "local"
    assert seen_payload["top_k"] == 10
    assert seen_payload["response_type"] == "Bullet Points"
    assert seen_payload["include_references"] is False


async def test_query_error_propagates_as_lightrag_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "query cannot be empty"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await query(ctx, query="")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "query cannot be empty"


async def test_query_data_always_includes_references_and_skips_llm_flags() -> None:
    seen_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/query/data"
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "ok",
                "data": {"entities": []},
                "metadata": {},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await query_data(ctx, query="find DIME entities", mode="global")

    assert result["status"] == "success"
    assert seen_payload["include_references"] is True
    assert seen_payload["mode"] == "global"
    assert "only_need_context" not in seen_payload
    assert "only_need_prompt" not in seen_payload


async def test_query_data_error_propagates_as_lightrag_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGConnectionError):
        await query_data(ctx, query="hi")


async def test_query_uses_client_query_timeout() -> None:
    """/query can run an LLM call, so it must use the client's dedicated
    query_timeout rather than the general-purpose timeout."""
    seen_timeout: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "ok"})

    ctx, client = make_ctx(handler, timeout=5.0, query_timeout=120.0)
    assert client.query_timeout == 120.0

    # Patch _send to observe the timeout argument it receives.
    original_send = client._send

    async def spy_send(method, path, **kwargs):
        seen_timeout.append(kwargs.get("timeout"))
        return await original_send(method, path, **kwargs)

    client._send = spy_send  # type: ignore[method-assign]

    await query(ctx, query="hi")

    assert seen_timeout == [120.0]
