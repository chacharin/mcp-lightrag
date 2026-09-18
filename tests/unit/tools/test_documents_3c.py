"""Unit tests for tools/documents.py round 3C (delete/pipeline control) tools."""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.documents import (
    cancel_pipeline,
    clear_all_documents,
    delete_documents,
    force_reset_recovery,
    repair_source_conflict,
)
from tests.unit.conftest import make_ctx


async def test_delete_documents_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/documents/delete_document"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "deletion_started", "doc_id": "doc-1", "message": "ok"}
        )

    ctx, _client = make_ctx(handler)
    result = await delete_documents(ctx, doc_ids=["doc-1"], delete_file=True)

    assert result["status"] == "deletion_started"
    assert seen_body == {
        "doc_ids": ["doc-1"],
        "delete_file": True,
        "delete_llm_cache": False,
    }


async def test_delete_documents_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "pipeline busy"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await delete_documents(ctx, doc_ids=["doc-1"])

    assert exc_info.value.status_code == 503


async def test_clear_all_documents_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/documents"
        assert request.url.params["delete_parsed_files"] == "false"
        assert request.url.params["clear_llm_cache"] == "true"
        return httpx.Response(200, json={"status": "success", "message": "cleared"})

    ctx, _client = make_ctx(handler)
    result = await clear_all_documents(ctx, clear_llm_cache=True)

    assert result["status"] == "success"


async def test_clear_all_documents_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await clear_all_documents(ctx)


async def test_force_reset_recovery_requires_confirm_true_to_reset() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "reset",
                "message": "cleared",
                "cancelled_manual_retries": 0,
                "dropped_enqueue_reservations": 0,
                "retained_enqueue_reservations": 0,
            },
        )

    ctx, _client = make_ctx(handler)
    result = await force_reset_recovery(ctx, confirm=True)

    assert result["status"] == "reset"
    assert seen_body == {"confirm": True}


async def test_force_reset_recovery_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await force_reset_recovery(ctx, confirm=True)


async def test_cancel_pipeline_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/cancel_pipeline"
        return httpx.Response(
            200, json={"status": "cancellation_requested", "message": "ok"}
        )

    ctx, _client = make_ctx(handler)
    result = await cancel_pipeline(ctx)

    assert result["status"] == "cancellation_requested"


async def test_cancel_pipeline_not_busy() -> None:
    """Not an error case for the client -- LightRAG reports not_busy as a
    normal 200, and the tool must pass that through as-is rather than
    inventing an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "not_busy", "message": "nothing running"}
        )

    ctx, _client = make_ctx(handler)
    result = await cancel_pipeline(ctx)

    assert result["status"] == "not_busy"


async def test_cancel_pipeline_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await cancel_pipeline(ctx)


async def test_repair_source_conflict_dry_run_default() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "canonical_source_key": "a.pdf",
                "primary_doc_id": "doc-1",
                "candidate_count": 2,
                "fingerprint": "abc123",
                "demoted_sample_doc_ids": ["doc-2"],
                "committed": False,
            },
        )

    ctx, _client = make_ctx(handler)
    result = await repair_source_conflict(
        ctx, canonical_source_key="a.pdf", primary_doc_id="doc-1"
    )

    assert result["committed"] is False
    assert seen_body == {
        "canonical_source_key": "a.pdf",
        "primary_doc_id": "doc-1",
        "dry_run": True,
    }


async def test_repair_source_conflict_commit_sends_cas_tokens() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "canonical_source_key": "a.pdf",
                "primary_doc_id": "doc-1",
                "candidate_count": 2,
                "fingerprint": "abc123",
                "demoted_sample_doc_ids": ["doc-2"],
                "committed": True,
            },
        )

    ctx, _client = make_ctx(handler)
    result = await repair_source_conflict(
        ctx,
        canonical_source_key="a.pdf",
        primary_doc_id="doc-1",
        dry_run=False,
        expected_candidate_count=2,
        expected_candidate_fingerprint="abc123",
    )

    assert result["committed"] is True
    assert seen_body == {
        "canonical_source_key": "a.pdf",
        "primary_doc_id": "doc-1",
        "dry_run": False,
        "expected_candidate_count": 2,
        "expected_candidate_fingerprint": "abc123",
    }


async def test_repair_source_conflict_commit_missing_tokens_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "detail": (
                    "expected_candidate_count and expected_candidate_fingerprint are "
                    "required when dry_run is false"
                )
            },
        )

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await repair_source_conflict(
            ctx, canonical_source_key="a.pdf", primary_doc_id="doc-1", dry_run=False
        )

    assert exc_info.value.status_code == 422
