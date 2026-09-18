"""System tools: `health` (plan.md section 4.4).

Every tool function here is a plain top-level async function so
tests/unit/tools/test_system.py can import and call it directly with a
fake ctx, instead of going through the MCP protocol machinery.
`register()` is the only thing server.py calls.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from mcp_lightrag.tools._common import get_client


async def health(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Check whether LightRAG is reachable AND whether this server's
    credentials actually work. `GET /health` alone is not enough: it is a
    public liveness probe that returns 200 even with a missing or wrong API
    key, so this tool also calls `get_document_status_counts` (which does
    enforce auth) and lets any failure from that call raise -- this tool
    never reports healthy while authentication is broken, which was the
    old lightrag-mcp wrapper's exact trap."""
    client = get_client(ctx)
    status = await client.request("GET", "/health")
    document_status_counts = await client.request("GET", "/documents/status_counts")
    return {**status, "document_status_counts": document_status_counts}


def register(server: MCPServer[Any]) -> None:
    server.add_tool(health)
