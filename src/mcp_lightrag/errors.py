"""Exceptions raised by the LightRAG HTTP client.

Every failure calling LightRAG -- an HTTP error response, a timeout, or a
connection failure -- becomes one of the exceptions below rather than a
falsy/None-shaped "success". A tool implementation lets these propagate:
MCPServer turns a raised exception into an MCP tool error, which is what
tells the calling agent "this failed" instead of "there is no data".

This directly targets the bug this project exists to fix: the community
lightrag-mcp wrapper's generated client silently turned any non-200/422
response into `None`, which its formatter then rendered as the literal
string "None" inside a `{"status": "success", ...}` envelope.

Subclassing `mcp`'s own `ToolError` matters just as much as the message
text: `mcp.server.mcpserver`'s tool runner only forwards an exception's
message to the calling agent when it is a `ToolError` (an "anticipated"
failure) -- any other exception is treated as a crash and replaced with a
bare "Error executing tool <name>", discarding everything below. Found the
hard way in Phase 6: `insert_text` raised a plain-`Exception`-based
`LightRAGError` with a precise "A valid file_source is required" message,
and Hermes still only ever saw "Error executing tool insert_text", because
`LightRAGClientError` didn't inherit from `ToolError`. Without this base
class, every one of this client's errors -- not just this one -- would
reach the agent as that same content-free message, silently reintroducing
the "fails, but doesn't say why" bug this project exists to fix.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class LightRAGClientError(ToolError):
    """Base class for every error this client raises."""


class LightRAGError(LightRAGClientError):
    """LightRAG responded, but with a non-2xx HTTP status."""

    def __init__(self, status_code: int, method: str, path: str, detail: str) -> None:
        self.status_code = status_code
        self.method = method
        self.path = path
        self.detail = detail
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"LightRAG {self.status_code} on {self.method} {self.path}: {self.detail}"
        )


class LightRAGConnectionError(LightRAGClientError):
    """LightRAG never responded: a timeout, or the connection itself failed."""

    def __init__(self, base_url: str, reason: str) -> None:
        self.base_url = base_url
        self.reason = reason
        super().__init__(str(self))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"LightRAG unreachable at {self.base_url} ({self.reason})"
