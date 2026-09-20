"""Unit tests for audit.py (plan.md section 7.3.2: classification labelling
and audit logging, phase 7's addition to mcp-lightrag).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from mcp_types import CallToolResult, TextContent

from mcp_lightrag.audit import (
    _configure_audit_logger,
    _hash_params,
    _label_result,
    build_audit_middleware,
)
from mcp_lightrag.config import Settings


def _dict_result(data: dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    """A CallToolResult shaped exactly like what `convert_result` builds for
    one of this project's tools (all declared `-> dict[str, Any]`): a single
    TextContent holding the JSON dump, plus the same dict as
    structured_content -- see func_metadata.py's `convert_result`.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structured_content=dict(data),
        is_error=is_error,
    )


class TestHashParams:
    def test_same_arguments_same_hash(self) -> None:
        assert _hash_params({"a": 1, "b": 2}) == _hash_params({"a": 1, "b": 2})

    def test_key_order_does_not_matter(self) -> None:
        assert _hash_params({"a": 1, "b": 2}) == _hash_params({"b": 2, "a": 1})

    def test_different_arguments_different_hash(self) -> None:
        assert _hash_params({"a": 1}) != _hash_params({"a": 2})

    def test_never_contains_the_argument_values(self) -> None:
        digest = _hash_params({"query": "TOP SECRET PROJECT NAME"})
        assert "TOP SECRET PROJECT NAME" not in digest


class TestLabelResult:
    def test_attaches_classification_to_structured_and_text_content(self) -> None:
        result = _dict_result({"docs": 5})

        labelled = _label_result(result, "ลับมาก")

        assert labelled.structured_content == {"docs": 5, "classification": "ลับมาก"}
        assert json.loads(labelled.content[0].text) == {
            "docs": 5,
            "classification": "ลับมาก",
        }

    def test_noop_when_no_classification_configured(self) -> None:
        result = _dict_result({"docs": 5})

        labelled = _label_result(result, "")

        assert labelled.structured_content == {"docs": 5}
        assert json.loads(labelled.content[0].text) == {"docs": 5}

    def test_noop_on_error_result(self) -> None:
        """An error result has nothing meaningful to classify, and must not
        gain a fabricated classification tag."""
        result = _dict_result({"detail": "boom"}, is_error=True)

        labelled = _label_result(result, "ลับที่สุด")

        assert labelled.structured_content == {"detail": "boom"}
        assert "classification" not in json.loads(labelled.content[0].text)


class TestConfigureAuditLogger:
    def test_writes_to_file_when_path_given(self, tmp_path: Any) -> None:
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
        log_path = tmp_path / "audit.jsonl"

        audit_logger = _configure_audit_logger(str(log_path))
        audit_logger.info(json.dumps({"tool": "health"}))
        for handler in audit_logger.handlers:
            handler.flush()

        line = log_path.read_text(encoding="utf-8").strip()
        assert json.loads(line) == {"tool": "health"}
        audit_logger.handlers.clear()

    def test_idempotent_does_not_attach_a_second_handler(self, tmp_path: Any) -> None:
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
        log_path = tmp_path / "audit.jsonl"

        logger1 = _configure_audit_logger(str(log_path))
        logger2 = _configure_audit_logger(str(log_path))

        assert logger1 is logger2
        assert len(logger1.handlers) == 1
        logger1.handlers.clear()


class _FakeCtx:
    def __init__(self, method: str, params: dict[str, Any] | None) -> None:
        self.method = method
        self.params = params


async def _call_next_returning(result: CallToolResult) -> CallToolResult:
    return result


class TestAuditMiddleware:
    def _settings(self, monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
        """Settings(), the same way every other test in this suite would
        resolve it (see tests/integration/conftest.py) -- from the process
        environment, never from constructor kwargs, since Settings' fields
        use `validation_alias` without `populate_by_name`, so only the env
        var name (e.g. MCP_AUDIT_LOG), not the Python field name, is a
        valid way to set them."""
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings()

    async def test_passes_through_non_tool_call_methods_unlogged(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
        log_path = tmp_path / "audit.jsonl"
        middleware = build_audit_middleware(
            self._settings(monkeypatch, MCP_AUDIT_LOG=str(log_path))
        )
        ctx = _FakeCtx("resources/list", {})

        result = await middleware(ctx, lambda _ctx: _call_next_returning(None))  # type: ignore[arg-type]

        assert result is None
        # _configure_audit_logger's FileHandler creates the file eagerly
        # (delay=False), but a passthrough call must never write a line to it
        assert log_path.read_text(encoding="utf-8") == ""
        logging.getLogger("mcp_lightrag.audit").handlers.clear()

    async def test_logs_and_labels_a_successful_tool_call(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
        log_path = tmp_path / "audit.jsonl"
        settings = self._settings(
            monkeypatch,
            MCP_AUDIT_LOG=str(log_path),
            MCP_CLASSIFICATION_LABEL="ลับ",
        )
        middleware = build_audit_middleware(settings)
        ctx = _FakeCtx("tools/call", {"name": "health", "arguments": {}})
        raw_result = _dict_result({"status": "healthy"})

        labelled = await middleware(ctx, lambda _ctx: _call_next_returning(raw_result))

        assert labelled.structured_content["classification"] == "ลับ"
        for handler in logging.getLogger("mcp_lightrag.audit").handlers:
            handler.flush()
        event = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert event["tool"] == "health"
        assert event["classification"] == "ลับ"
        assert event["status"] == "success"
        assert set(event) == {
            "timestamp",
            "tool",
            "classification",
            "params_hash",
            "status",
        }
        # the tool's actual result content must never end up in the audit line
        assert "healthy" not in log_path.read_text(encoding="utf-8")
        logging.getLogger("mcp_lightrag.audit").handlers.clear()

    async def test_logs_error_status_and_reraises(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
        log_path = tmp_path / "audit.jsonl"
        middleware = build_audit_middleware(
            self._settings(monkeypatch, MCP_AUDIT_LOG=str(log_path))
        )
        ctx = _FakeCtx(
            "tools/call",
            {"name": "query", "arguments": {"query": "TOP SECRET PROJECT NAME"}},
        )

        async def _boom(_ctx: Any) -> CallToolResult:
            raise RuntimeError("LightRAG unreachable")

        with pytest.raises(RuntimeError):
            await middleware(ctx, _boom)

        for handler in logging.getLogger("mcp_lightrag.audit").handlers:
            handler.flush()
        raw_log = log_path.read_text(encoding="utf-8")
        event = json.loads(raw_log.strip())
        assert event["status"] == "error"
        assert "LightRAG unreachable" in event["error"]
        assert event["tool"] == "query"
        # the raw argument value itself must never end up in the audit line,
        # only its hash (plan.md 7.3.2c) -- "tool": "query" is expected and
        # fine, the *value* of the "query" argument is what must never leak
        assert "TOP SECRET PROJECT NAME" not in raw_log
        logging.getLogger("mcp_lightrag.audit").handlers.clear()
