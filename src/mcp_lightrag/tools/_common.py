"""Shared helpers for tool modules.

Not a "tools" module itself -- nothing here is registered with the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context

if TYPE_CHECKING:
    from mcp_lightrag.client import LightRAGClient
    from mcp_lightrag.server import AppContext


def get_client(ctx: Context[Any, Any]) -> LightRAGClient:
    """Pull the shared LightRAGClient out of the server's lifespan context.

    Every tool takes `ctx: Context[AppContext, Any]` as its last parameter
    (MCPServer injects it automatically -- it is never passed by the
    calling agent) and starts its body with `client = get_client(ctx)`.
    """
    app_context: AppContext = ctx.request_context.lifespan_context
    return app_context.client
