"""Registers every tool this server exposes onto an MCPServer instance.

Tools are split by domain (plan.md section 4): query.py, documents.py,
graph.py, system.py. Each module owns a `register(server)` function; this
package's `register_all` is the single call site server.py uses.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mcp_lightrag.tools import documents, graph, query, system


def register_all(server: MCPServer[Any]) -> None:
    system.register(server)
    query.register(server)
    documents.register(server)
    graph.register(server)
