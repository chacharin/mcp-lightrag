"""Unit tests for tools/system.py (`health`)."""

from __future__ import annotations

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.system import health
from tests.unit.conftest import make_ctx


async def test_health_merges_status_and_document_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(
                200, json={"status": "healthy", "auth_mode": "enabled"}
            )
        assert request.url.path == "/documents/status_counts"
        return httpx.Response(200, json={"status_counts": {"processed": 5}})

    ctx, _client = make_ctx(handler, api_key="correct-key")
    result = await health(ctx)

    assert result["status"] == "healthy"
    assert result["auth_mode"] == "enabled"
    assert result["document_status_counts"] == {"status_counts": {"processed": 5}}


async def test_health_raises_when_api_key_is_wrong() -> None:
    """/health is a public liveness probe and returns 200 even with a bad
    key; /documents/status_counts does enforce auth, so a bad key must
    surface as a failure here, not a fake "healthy"."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        return httpx.Response(
            403, json={"detail": "API Key required or incorrect API Key"}
        )

    ctx, _client = make_ctx(handler, api_key="wrong-key")

    with pytest.raises(LightRAGError) as exc_info:
        await health(ctx)

    assert exc_info.value.status_code == 403
