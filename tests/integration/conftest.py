"""Shared helpers for the Phase 4.5 integration tests.

Unlike tests/unit/conftest.py's make_ctx (which wires a LightRAGClient to
an httpx2.MockTransport), build_ctx here builds a LightRAGClient that
makes real network calls, configured the exact same way `mcp-lightrag`
itself is: from Settings(), which resolves LIGHTRAG_URL / LIGHTRAG_API_KEY
/ etc. from the environment (see plan.md Phase 4.5 and .env.example).

Every test in this package is marked `integration` and is excluded by
default (see pyproject.toml's `addopts = "-m 'not integration'"`) --
run explicitly with:

    LIGHTRAG_URL=http://localhost:9622 uv run pytest tests/integration -m integration

against a disposable LightRAG instance. Never point this at a real
knowledge base: test_lightrag_integration.py ends by clearing every
document the instance holds.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from mcp_lightrag.client import LightRAGClient
from mcp_lightrag.config import Settings


def build_ctx(client: LightRAGClient) -> Any:
    """Same fake-Context shape as tests/unit/conftest.py's make_ctx, so the
    real top-level tool functions (list_documents, query, ...) can be
    called directly without MCP protocol machinery."""
    return SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(client=client))
    )


@asynccontextmanager
async def make_real_client() -> AsyncIterator[LightRAGClient]:
    """`async with make_real_client() as client:` -- builds a LightRAGClient
    exactly the way `mcp-lightrag` itself does, from Settings() resolved
    out of the environment, and closes it afterwards.
    """
    settings = Settings()
    client = LightRAGClient(
        base_url=settings.lightrag_url,
        api_key=settings.lightrag_api_key,
        username=settings.lightrag_username,
        password=settings.lightrag_password,
        timeout=settings.timeout,
        query_timeout=settings.query_timeout,
        upload_timeout=settings.upload_timeout,
        verify_ssl=settings.verify_ssl,
    )
    try:
        yield client
    finally:
        await client.aclose()


async def poll_until[T](
    predicate: Callable[[], Awaitable[T | None]],
    *,
    timeout: float = 120.0,
    interval: float = 3.0,
    description: str = "condition",
) -> T:
    """Call `predicate` every `interval` seconds until it returns a
    truthy, non-None value, or raise AssertionError after `timeout`
    seconds. Used to wait for LightRAG's background indexing/deletion
    (insert_text, delete_documents, ... all return immediately and finish
    asynchronously) instead of a single fixed sleep.
    """
    elapsed = 0.0
    while elapsed < timeout:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(interval)
        elapsed += interval
    raise AssertionError(f"Timed out after {timeout}s waiting for: {description}")
