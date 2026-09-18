"""Async HTTP client for the LightRAG REST API.

Owns exactly three things: authentication (an X-API-Key header, or JWT
login + one-time renewal when LIGHTRAG_USERNAME/PASSWORD are set), turning
every non-2xx response into a LightRAGError with a readable message, and
turning every transport-level failure (timeout, connection refused) into a
LightRAGConnectionError. It does not know about individual LightRAG
endpoints beyond the ENDPOINTS registry below -- tools/*.py (Phase 3) call
`request()` with their own method/path/body and get back decoded JSON or a
raised exception.

ENDPOINTS is a flat list of every (method, path) pair this project uses,
including ones no tool calls yet in Phase 2. scripts/check_api_compat.py
(Phase 4) reads it to check every pair still exists in the live server's
/openapi.json, so this is the one place a future LightRAG API change would
need a matching update here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Self

import httpx2 as httpx

from mcp_lightrag.errors import LightRAGConnectionError, LightRAGError

logger = logging.getLogger(__name__)

# (method, path, tool name). Path is the literal template as LightRAG's
# OpenAPI spec documents it (path parameters use FastAPI's "{name}" form).
# "_login" isn't a tool -- it's this client's own use of /login for the
# optional JWT flow -- listed here so check_api_compat.py verifies it too.
ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("GET", "/health", "health"),
    ("POST", "/login", "_login"),
    ("POST", "/query", "query"),
    ("POST", "/query/data", "query_data"),
    ("POST", "/documents/paginated", "list_documents"),
    ("GET", "/documents/status_counts", "get_document_status_counts"),
    ("GET", "/documents/pipeline_status", "get_pipeline_status"),
    ("GET", "/documents/track_status/{track_id}", "get_track_status"),
    ("POST", "/documents/text", "insert_text"),
    ("POST", "/documents/texts", "insert_texts"),
    ("POST", "/documents/upload", "upload_file"),
    ("GET", "/documents/supported_file_types", "get_supported_file_types"),
    ("POST", "/documents/scan", "scan_documents"),
    ("GET", "/documents/scan/status/{track_id}", "get_scan_status"),
    ("POST", "/documents/reprocess_failed", "reprocess_failed_documents"),
    ("POST", "/documents/cancel_pipeline", "cancel_pipeline"),
    ("GET", "/documents/source_conflicts", "list_source_conflicts"),
    ("POST", "/documents/source_conflicts/repair", "repair_source_conflict"),
    ("DELETE", "/documents/delete_document", "delete_documents"),
    ("DELETE", "/documents", "clear_all_documents"),
    ("POST", "/documents/recovery/force_reset", "force_reset_recovery"),
    ("GET", "/graph/label/list", "get_graph_labels"),
    ("GET", "/graph/label/popular", "get_popular_labels"),
    ("GET", "/graph/label/search", "search_labels"),
    ("GET", "/graphs", "get_knowledge_graph"),
    ("GET", "/graph/entity/exists", "check_entity_exists"),
    ("POST", "/graph/entity/create", "create_entity"),
    ("POST", "/graph/entity/edit", "edit_entity"),
    ("POST", "/graph/relation/create", "create_relation"),
    ("POST", "/graph/relation/edit", "edit_relation"),
    ("POST", "/graph/entities/merge", "merge_entities"),
    ("DELETE", "/graph/entity/delete", "delete_entity"),
    ("DELETE", "/graph/relation/delete", "delete_relation"),
)


class LightRAGClient:
    """Thin async wrapper around LightRAG's REST API.

    Usage::

        async with LightRAGClient(base_url=..., api_key=...) as client:
            data = await client.request("GET", "/documents/status_counts")
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
        query_timeout: float | None = None,
        upload_timeout: float | None = None,
        verify_ssl: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._username = username
        self._password = password
        self._jwt: str | None = None
        # /query and /query/data can run an LLM call, and file uploads can
        # take much longer than an ordinary metadata request -- tools that
        # hit those endpoints pass client.query_timeout / client.upload_timeout
        # as their own per-call override. Both fall back to the general
        # `timeout` when not given their own value (e.g. in tests).
        self.query_timeout = query_timeout if query_timeout is not None else timeout
        self.upload_timeout = upload_timeout if upload_timeout is not None else timeout
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            verify=verify_ssl,
            # Test seam only: production callers never pass this, and rely
            # on the real network transport. Unit tests (tests/unit/test_client.py)
            # pass an httpx2.MockTransport here per plan.md's Phase 4.2 approach.
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        # Sent unconditionally when configured -- LightRAG accepts X-API-Key
        # and a JWT Authorization header together (the WebUI does this too),
        # so there is no reason to choose one over the other here.
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        if self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        return headers

    async def _login(self) -> None:
        """Fetch a fresh JWT using LIGHTRAG_USERNAME/PASSWORD.

        LightRAG's /login expects an OAuth2 password-flow form body (field
        names "username"/"password"), not JSON -- confirmed against
        lightrag/api/lightrag_server.py's `login()` handler, which declares
        `form_data: OAuth2PasswordRequestForm = Depends()`.
        """
        response = await self._send(
            "POST",
            "/login",
            data={"username": self._username, "password": self._password},
            headers={},
            retry_get_on_connect_error=False,
        )
        self._raise_for_status(response, "POST", "/login")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise LightRAGError(
                response.status_code, "POST", "/login", "response had no access_token"
            )
        self._jwt = token

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or response.reason_phrase
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail:
                return detail
            if detail is not None:
                return str(detail)
        return response.reason_phrase

    def _raise_for_status(
        self, response: httpx.Response, method: str, path: str
    ) -> None:
        if response.status_code >= 400:
            raise LightRAGError(
                response.status_code, method, path, self._extract_detail(response)
            )

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        params: Mapping[str, Any] | None = None,
        files: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        retry_get_on_connect_error: bool = True,
    ) -> httpx.Response:
        """Issue one HTTP call, converting transport failures to
        LightRAGConnectionError. A GET is retried once on a connect error
        (a transient blip, e.g. right after container startup, is far more
        likely than a real outage); POST/DELETE are never retried
        automatically, since retrying a request with side effects risks
        inserting or deleting data twice. A timeout is never retried
        either way -- the server may have already accepted a write.
        """
        merged_headers = dict(headers if headers is not None else self._auth_headers())
        request_timeout = httpx.Timeout(timeout) if timeout is not None else None
        attempts = 2 if (method == "GET" and retry_get_on_connect_error) else 1

        for attempt in range(attempts):
            try:
                return await self._http.request(
                    method,
                    path,
                    json=json,
                    data=data,
                    params=params,
                    files=files,
                    headers=merged_headers,
                    timeout=request_timeout,
                )
            except httpx.ConnectError as exc:
                if attempt + 1 < attempts:
                    logger.warning(
                        "Connect error on %s %s, retrying once: %s", method, path, exc
                    )
                    continue
                raise LightRAGConnectionError(self._base_url, "connect error") from exc
            except httpx.TimeoutException as exc:
                raise LightRAGConnectionError(self._base_url, "timed out") from exc

        # Unreachable (the loop above always returns or raises), but keeps
        # type-checkers from complaining about a possible fall-through.
        raise AssertionError("unreachable")

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        files: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """Call a LightRAG endpoint and return its decoded JSON body (or
        None for an empty response body).

        Every non-2xx response raises LightRAGError; every timeout or
        connection failure raises LightRAGConnectionError -- callers should
        let both propagate rather than catching them, so a raised exception
        reaches the agent as a real MCP tool error instead of a disguised
        "success".

        On a 401, and only when username/password are configured, this logs
        in once for a fresh JWT and retries the original request once
        before giving up.
        """
        response = await self._send(
            method, path, json=json, params=params, files=files, timeout=timeout
        )
        if response.status_code == 401 and self._username and self._password:
            await self._login()
            response = await self._send(
                method, path, json=json, params=params, files=files, timeout=timeout
            )
        self._raise_for_status(response, method, path)
        if not response.content:
            return None
        return response.json()
