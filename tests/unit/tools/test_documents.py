"""Unit tests for tools/documents.py round 3A (read-only) tools."""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGConnectionError, LightRAGError
from mcp_lightrag.tools.documents import (
    get_document_status_counts,
    get_pipeline_status,
    get_scan_status,
    get_supported_file_types,
    get_track_status,
    list_documents,
    list_source_conflicts,
)
from tests.unit.conftest import make_ctx

_RAW_DOC = {
    "id": "doc-1",
    "content_summary": "long summary text that should be dropped",
    "content_length": 12345,
    "file_path": "joc-1-การอำนวยการ.md",
    "status": "processed",
    "created_at": "2025-03-31T12:34:56",
    "updated_at": "2025-03-31T12:35:30",
    "track_id": "upload_123",
    "chunks_count": 12,
    "metadata": {"author": "someone"},
}


async def test_list_documents_trims_fields_and_reports_pagination() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/paginated"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "documents": [_RAW_DOC],
                "pagination": {
                    "page": 1,
                    "page_size": 50,
                    "total_count": 5,
                    "total_pages": 1,
                    "has_next": False,
                    "has_prev": False,
                },
                "status_counts": {"processed": 5},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await list_documents(ctx)

    assert seen_body["page"] == 1
    assert seen_body["page_size"] == 50
    assert "status_filter" not in seen_body
    assert result["total_count"] == 5
    assert result["has_next"] is False
    doc = result["documents"][0]
    assert doc == {
        "id": "doc-1",
        "file_path": "joc-1-การอำนวยการ.md",
        "status": "processed",
        "chunks_count": 12,
        "updated_at": "2025-03-31T12:35:30",
    }
    assert "content_summary" not in doc
    assert "metadata" not in doc


async def test_list_documents_includes_error_msg_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        failed_doc = {**_RAW_DOC, "status": "failed", "error_msg": "parse error"}
        return httpx.Response(
            200,
            json={
                "documents": [failed_doc],
                "pagination": {
                    "page": 1,
                    "page_size": 50,
                    "total_count": 1,
                    "total_pages": 1,
                    "has_next": False,
                    "has_prev": False,
                },
                "status_counts": {"failed": 1},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await list_documents(ctx, status_filter="failed")

    assert result["documents"][0]["error_msg"] == "parse error"


async def test_list_documents_sends_status_filter_when_given() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "documents": [],
                "pagination": {
                    "page": 1,
                    "page_size": 50,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
                "status_counts": {},
            },
        )

    ctx, _client = make_ctx(handler)
    await list_documents(ctx, status_filter="processed", page=2, page_size=10)

    assert seen_body["status_filter"] == "processed"
    assert seen_body["page"] == 2
    assert seen_body["page_size"] == 10


async def test_list_documents_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await list_documents(ctx)

    assert exc_info.value.status_code == 500


async def test_get_document_status_counts_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/status_counts"
        return httpx.Response(
            200, json={"status_counts": {"processed": 5, "failed": 1}}
        )

    ctx, _client = make_ctx(handler)
    result = await get_document_status_counts(ctx)

    assert result == {"status_counts": {"processed": 5, "failed": 1}}


async def test_get_document_status_counts_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Not authenticated"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await get_document_status_counts(ctx)

    assert exc_info.value.status_code == 401


_RAW_PIPELINE = {
    "busy": True,
    "job_name": "Indexing files",
    "job_start": "2025-03-31T12:00:00+00:00",
    "docs": 5,
    "batchs": 2,
    "cur_batch": 1,
    "latest_message": "Processing chunk 3/10",
    "history_messages": [f"line {i}" for i in range(30)],
    "update_status": {"ns1": "big blob" * 1000},
    "recovery_required": False,
    "recovery_kind": None,
    "recovery_message": None,
}


async def test_get_pipeline_status_returns_condensed_summary_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_RAW_PIPELINE)

    ctx, _client = make_ctx(handler)
    result = await get_pipeline_status(ctx)

    assert result["busy"] is True
    assert result["job_name"] == "Indexing files"
    assert len(result["history_messages"]) == 10
    assert result["history_messages"] == [f"line {i}" for i in range(20, 30)]
    assert "update_status" not in result


async def test_get_pipeline_status_verbose_returns_full_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_RAW_PIPELINE)

    ctx, _client = make_ctx(handler)
    result = await get_pipeline_status(ctx, verbose=True)

    assert "update_status" in result
    assert len(result["history_messages"]) == 30


async def test_get_pipeline_status_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGConnectionError):
        await get_pipeline_status(ctx)


async def test_get_track_status_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/track_status/upload_123"
        return httpx.Response(
            200,
            json={
                "track_id": "upload_123",
                "documents": [_RAW_DOC],
                "total_count": 1,
                "status_summary": {"processed": 1},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await get_track_status(ctx, track_id="upload_123")

    assert result["track_id"] == "upload_123"
    assert result["documents"][0]["id"] == "doc-1"
    assert result["status_summary"] == {"processed": 1}


async def test_get_track_status_not_found_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "No track_id found: bogus"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await get_track_status(ctx, track_id="bogus")

    assert exc_info.value.status_code == 404


async def test_get_supported_file_types_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "supported_extensions": [".pdf", ".md"],
                "engines": {"legacy": [".pdf", ".md"]},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await get_supported_file_types(ctx)

    assert ".pdf" in result["supported_extensions"]


async def test_get_supported_file_types_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await get_supported_file_types(ctx)


async def test_get_scan_status_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/scan/status/scan_123"
        return httpx.Response(
            200,
            json={
                "track_id": "scan_123",
                "status": "completed",
                "counts": {"processed": 3},
                "samples": {},
                "created_at": 1.0,
                "updated_at": 2.0,
                "version": 1,
                "message": "done",
            },
        )

    ctx, _client = make_ctx(handler)
    result = await get_scan_status(ctx, track_id="scan_123")

    assert result["status"] == "completed"


async def test_get_scan_status_not_found_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"detail": "No scan job found for track_id bogus"}
        )

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await get_scan_status(ctx, track_id="bogus")

    assert exc_info.value.status_code == 404


async def test_list_source_conflicts_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "50"
        return httpx.Response(
            200,
            json={
                "conflicts": [
                    {
                        "canonical_source_key": "a.pdf",
                        "candidate_count": 2,
                        "sample_doc_ids": ["d1", "d2"],
                    }
                ],
                "next_cursor": None,
            },
        )

    ctx, _client = make_ctx(handler)
    result = await list_source_conflicts(ctx)

    assert result["conflicts"][0]["canonical_source_key"] == "a.pdf"
    assert result["next_cursor"] is None


async def test_list_source_conflicts_sends_cursor_when_given() -> None:
    seen_params: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"conflicts": [], "next_cursor": None})

    ctx, _client = make_ctx(handler)
    await list_source_conflicts(ctx, limit=10, cursor="opaque-cursor")

    assert seen_params["cursor"] == "opaque-cursor"
    assert seen_params["limit"] == "10"


async def test_list_source_conflicts_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(501, json={"detail": "not supported"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await list_source_conflicts(ctx)

    assert exc_info.value.status_code == 501
