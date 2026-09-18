"""Shared test helpers for tool unit tests.

Tool functions are plain top-level async functions (see tools/_common.py's
docstring) that take `ctx` and pull the LightRAGClient out of
`ctx.request_context.lifespan_context.client`. `make_ctx` builds the
smallest object shaped like that -- a real LightRAGClient wired to an
httpx2.MockTransport, wrapped in bare SimpleNamespaces standing in for the
real Context/ServerRequestContext/AppContext -- so a tool function can be
called directly without going through MCP protocol machinery.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx2 as httpx

from mcp_lightrag.client import LightRAGClient

BASE_URL = "http://lightrag.test"


def make_ctx(
    handler: Callable[[httpx.Request], httpx.Response],
    **client_kwargs: Any,
) -> tuple[Any, LightRAGClient]:
    """Return (fake_ctx, client) for a tool function under test.

    `handler` plays the role of the LightRAG server: given a request, it
    returns the response. Extra kwargs (api_key, username/password, ...)
    are forwarded to LightRAGClient.
    """
    client = LightRAGClient(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        **client_kwargs,
    )
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(lifespan_context=SimpleNamespace(client=client))
    )
    return ctx, client
