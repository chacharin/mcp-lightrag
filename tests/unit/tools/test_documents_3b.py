"""Unit tests for tools/documents.py round 3B (add/edit) tools."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.documents import (
    insert_text,
    insert_texts,
    reprocess_failed_documents,
    scan_documents,
    upload_directory,
    upload_file,
)
from tests.unit.conftest import make_ctx

_SUPPORTED = {
    "supported_extensions": [".pdf", ".md", ".txt"],
    "engines": {"legacy": [".pdf", ".md", ".txt"]},
}


async def test_insert_text_success_sends_file_source() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/text"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "success", "message": "ok", "track_id": "t1"}
        )

    ctx, _client = make_ctx(handler)
    result = await insert_text(ctx, text="สวัสดี", file_source="note.md")

    assert result["track_id"] == "t1"
    assert seen_body == {"text": "สวัสดี", "file_source": "note.md"}


async def test_insert_text_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422, json={"detail": "text cannot be empty or whitespace-only"}
        )

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await insert_text(ctx, text="   ")

    assert exc_info.value.status_code == 422


async def test_insert_texts_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/texts"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "success", "message": "ok", "track_id": "t2"}
        )

    ctx, _client = make_ctx(handler)
    result = await insert_texts(ctx, texts=["a", "b"], file_sources=["s1", "s2"])

    assert result["track_id"] == "t2"
    assert seen_body == {"texts": ["a", "b"], "file_sources": ["s1", "s2"]}


async def test_insert_texts_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await insert_texts(ctx, texts=["a"])


async def test_upload_file_success(tmp_path) -> None:
    file_path = tmp_path / "report.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake content")

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/documents/supported_file_types":
            return httpx.Response(200, json=_SUPPORTED)
        assert request.url.path == "/documents/upload"
        return httpx.Response(
            200, json={"status": "success", "message": "uploaded", "track_id": "up1"}
        )

    ctx, _client = make_ctx(handler)
    result = await upload_file(ctx, path=str(file_path))

    assert result["track_id"] == "up1"
    assert calls == ["/documents/supported_file_types", "/documents/upload"]


async def test_upload_file_missing_file_raises_without_network_call() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_SUPPORTED)

    ctx, _client = make_ctx(handler)

    with pytest.raises(FileNotFoundError):
        await upload_file(ctx, path="/nonexistent/file.pdf")

    assert calls == []  # existence is checked before ever calling LightRAG


async def test_upload_file_unsupported_extension_raises(tmp_path) -> None:
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"PK\x03\x04")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUPPORTED)

    ctx, _client = make_ctx(handler)

    with pytest.raises(ValueError, match="Unsupported file extension"):
        await upload_file(ctx, path=str(file_path))


async def test_upload_directory_reports_per_file_results(tmp_path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"pdf-a")
    (tmp_path / "b.md").write_text("markdown content")
    (tmp_path / "c.zip").write_bytes(b"unsupported")
    (tmp_path / "sub").mkdir()  # directories are skipped, not treated as files

    upload_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_count
        if request.url.path == "/documents/supported_file_types":
            return httpx.Response(200, json=_SUPPORTED)
        assert request.url.path == "/documents/upload"
        upload_count += 1
        if upload_count == 1:
            return httpx.Response(
                200, json={"status": "success", "message": "ok", "track_id": "t-a"}
            )
        return httpx.Response(500, text="storage error")

    ctx, _client = make_ctx(handler)
    result = await upload_directory(ctx, directory=str(tmp_path))

    assert result["uploaded"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 1
    # str(entry) uses the platform's native separator (backslash on Windows),
    # so split("/") silently fails there -- Path(...).name handles either.
    statuses = {Path(r["file"]).name: r["status"] for r in result["results"]}
    assert statuses["a.pdf"] == "success"
    assert statuses["b.md"] == "error"
    assert statuses["c.zip"] == "skipped"


async def test_upload_directory_missing_directory_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SUPPORTED)

    ctx, _client = make_ctx(handler)

    with pytest.raises(NotADirectoryError):
        await upload_directory(ctx, directory="/nonexistent/dir")


async def test_scan_documents_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/documents/scan"
        return httpx.Response(
            200,
            json={"status": "scanning_started", "message": "ok", "track_id": "scan1"},
        )

    ctx, _client = make_ctx(handler)
    result = await scan_documents(ctx)

    assert result["track_id"] == "scan1"


async def test_scan_documents_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await scan_documents(ctx)


async def test_reprocess_failed_documents_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/documents/reprocess_failed"
        return httpx.Response(
            200,
            json={"status": "reprocessing_started", "message": "ok", "track_id": ""},
        )

    ctx, _client = make_ctx(handler)
    result = await reprocess_failed_documents(ctx)

    assert result["status"] == "reprocessing_started"


async def test_reprocess_failed_documents_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="pipeline busy")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await reprocess_failed_documents(ctx)
