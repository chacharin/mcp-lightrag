"""Regression test for the Phase 6 bug: `mcp.server.mcpserver`'s tool runner
only forwards an exception's message to the calling agent when it is a
`ToolError` (an "anticipated" failure) -- any other exception is treated as
a crash and replaced with a content-free "Error executing tool <name>".

`insert_text` raised a plain-`Exception`-based `LightRAGError` with a
precise "A valid file_source is required" message, and Hermes still only
ever saw "Error executing tool insert_text", because `LightRAGClientError`
didn't inherit from `ToolError`. This test exists so nobody can revert that
base class by accident without a test failing -- if it does, every one of
this client's errors goes back to reaching agents as that same
content-free message.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from mcp_lightrag.errors import (
    LightRAGClientError,
    LightRAGConnectionError,
    LightRAGError,
)


def test_lightrag_client_error_is_a_tool_error() -> None:
    assert issubclass(LightRAGClientError, ToolError)


def test_lightrag_error_instance_is_a_tool_error() -> None:
    err = LightRAGError(
        status_code=400,
        method="POST",
        path="/documents/text",
        detail="A valid file_source is required for text insertion",
    )
    assert isinstance(err, ToolError)
    assert isinstance(err, LightRAGClientError)
    assert (
        str(err)
        == "LightRAG 400 on POST /documents/text: A valid file_source is required for text insertion"
    )


def test_lightrag_connection_error_instance_is_a_tool_error() -> None:
    err = LightRAGConnectionError(
        base_url="http://lightrag:9621", reason="connect error"
    )
    assert isinstance(err, ToolError)
    assert isinstance(err, LightRAGClientError)
    assert str(err) == "LightRAG unreachable at http://lightrag:9621 (connect error)"
