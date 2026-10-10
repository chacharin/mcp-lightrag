"""Cross-cutting audit logging (plan.md section 7.3.2):

Write a JSON-lines audit log of every tool call: timestamp, tool name,
result status, and a hash of the parameters -- never the parameters or the
tool's return value themselves, so a sensitive query never ends up sitting
in a log file.

Implemented as a single `ServerMiddleware` (see server.py's `build_server`)
rather than by editing each of the 33 tool functions in tools/*.py: a
middleware wraps every `tools/call` request uniformly, at the JSON-RPC
level, so it never touches a tool function's signature -- which matters
here specifically, because `Tool.from_function` (mcp 2.x) inspects each
tool's *original* signature via `typing.get_type_hints` to find its
`Context` parameter and build its JSON argument schema. A generic wrapper
substituted in at registration time would carry its own `__globals__` (the
module it is defined in), and every tool file resolves different names in
its annotations (`QueryMode`, `Annotated`, `Field`, ...) via
`from __future__ import annotations` string annotations -- so a wrapper
defined anywhere but each tool's own module risks that lookup silently
failing. A middleware avoids the question entirely: every tool keeps
registering exactly as it does today, and a future 34th tool gets both
behaviors automatically, with nothing to remember to add to its body.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from mcp.server.context import (
    CallNext,
    HandlerResult,
    ServerMiddleware,
    ServerRequestContext,
)
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolResult

from mcp_lightrag.config import Settings

_AUDIT_LOGGER_NAME = "mcp_lightrag.audit"


def _configure_audit_logger(audit_log_path: str) -> logging.Logger:
    """Return the dedicated audit logger, writing one raw JSON object per
    line to `audit_log_path` if given, otherwise to stderr (plan.md 7.3.2c:
    "ลง stderr หรือไฟล์ที่กำหนดด้วย MCP_AUDIT_LOG"). It never uses cli.py's
    root `%(asctime)s - %(name)s - ...` formatter or propagates to it --
    each line must be bare, parseable JSON, not a log-formatted wrapper
    around one. Idempotent: calling this twice (e.g. if a process ever
    built two servers) does not attach a second handler.
    """
    audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
    if audit_logger.handlers:
        return audit_logger
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    handler: logging.Handler
    if audit_log_path:
        handler = logging.FileHandler(audit_log_path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
    return audit_logger


def _hash_params(arguments: dict[str, Any]) -> str:
    """SHA-256 of a tool call's arguments (canonical JSON: sorted keys, so
    the same arguments always hash the same way regardless of the order the
    calling agent supplied them in). Lets the audit log correlate repeated
    or identical calls without ever storing the argument values themselves,
    which may be sensitive (plan.md 7.3.2c: "hash ของพารามิเตอร์ (ไม่เก็บ
    เนื้อหาลับลง log)").
    """
    canonical = json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_audit_middleware(settings: Settings) -> ServerMiddleware[Any]:
    """Build the `ServerMiddleware` that `server.py`'s `build_server` passes
    to `MCPServer(..., middleware=[...])`.

    Bound to one `Settings` instance for the process's lifetime (same as
    every other setting in config.py): the audit log destination is fixed once
    at startup. Every `tools/call` request gets exactly one audit line --
    `status: "success"` or `"error"`. Every other request method
    (`initialize`, `resources/list`, ...) passes straight through untouched
    and unlogged.
    """
    audit_logger = _configure_audit_logger(settings.mcp_audit_log)

    async def audit_middleware(
        ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method != "tools/call" or ctx.params is None:
            return await call_next(ctx)

        tool_name = ctx.params.get("name", "<unknown>")
        arguments = ctx.params.get("arguments") or {}
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool_name,
            "params_hash": _hash_params(arguments),
        }

        try:
            result = await call_next(ctx)
        except MCPError as exc:
            event["status"] = "error"
            event["error"] = str(exc)
            audit_logger.info(json.dumps(event, ensure_ascii=True))
            raise
        except Exception as exc:
            event["status"] = "error"
            event["error"] = f"{type(exc).__name__}: {exc}"
            audit_logger.info(json.dumps(event, ensure_ascii=True))
            raise

        if isinstance(result, CallToolResult):
            event["status"] = "error" if result.is_error else "success"
        else:
            event["status"] = "success"

        audit_logger.info(json.dumps(event, ensure_ascii=True))
        return result

    return audit_middleware
