"""MCP server construction and lifespan.

Builds the `MCPServer` instance (mcp 2.x's renamed `FastMCP`), wires its
lifespan to open a single `LightRAGClient` on startup and close it on
shutdown, and registers every tool from `tools/` (plan.md section 4).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer

from mcp_lightrag.client import LightRAGClient
from mcp_lightrag.config import Settings
from mcp_lightrag.tools import register_all

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "This server bridges you to a LightRAG knowledge-graph instance. "
    "Use `query` to answer questions about the knowledge base's content. "
    "Use `get_document_status_counts` or `list_documents` when asked how "
    "many documents there are, or for a list of them -- do not assume the "
    "knowledge base is empty just because a tool call fails; a failure "
    "means LightRAG could not be reached or rejected the request, not that "
    "there are zero documents."
)


@dataclass
class AppContext:
    """What every tool receives via `ctx.request_context.lifespan_context`."""

    client: LightRAGClient


def build_server(settings: Settings) -> MCPServer[AppContext]:
    """Construct the MCPServer, with a lifespan that owns the LightRAGClient
    for the process's lifetime (opened on startup, closed on shutdown).
    """

    @asynccontextmanager
    async def app_lifespan(_server: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
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
        logger.info("LightRAG client ready for %s", settings.lightrag_url)
        try:
            yield AppContext(client=client)
        finally:
            await client.aclose()

    server = MCPServer(
        name=settings.server_name,
        instructions=INSTRUCTIONS,
        lifespan=app_lifespan,
    )
    register_all(server)
    return server


def run_server(args: argparse.Namespace) -> None:
    """Entry point called from cli.py: resolve Settings, build the server,
    and run it. `MCPServer.run()` is synchronous -- it drives its own event
    loop internally -- so this function is synchronous too.
    """
    settings = Settings.from_args(args)
    logging.getLogger().setLevel(settings.log_level)
    logger.info(
        "Starting mcp-lightrag %r (transport=%s, lightrag_url=%s)",
        settings.server_name,
        settings.transport,
        settings.lightrag_url,
    )
    server = build_server(settings)
    server.run(transport=settings.transport)
