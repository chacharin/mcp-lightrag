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
"""

from __future__ import annotations


class LightRAGClientError(Exception):
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
