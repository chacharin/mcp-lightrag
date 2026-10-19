"""lightrag_list_documents and lightrag_delete: what is sent to LightRAG, and when delete is offered at all."""
import asyncio
import json

import httpx
import pytest

from app import lightrag
from app.config import Settings
from tests.mcp_client import call, tools

DOCS = [
    {"id": "doc-aaa", "file_path": "monthly-report", "status": "processed", "content_length": 456,
     "content_summary": "# Monthly report\n\n1. sales", "created_at": "2026-10-18T04:33:14.516955+00:00",
     "metadata": {"chunk_method": "fixed_token"}, "error_msg": None},
    {"id": "doc-bbb", "file_path": "บันทึก-ประชุม", "status": "failed", "content_length": 10,
     "content_summary": "x", "created_at": "2026-10-17T16:25:47+00:00", "error_msg": "LLM timeout"},
    {"id": "doc-ccc", "file_path": "twin", "status": "processed", "content_summary": "", "created_at": ""},
    {"id": "doc-ddd", "file_path": "twin", "status": "processed", "content_summary": "", "created_at": ""},
]


def run(coro):
    return asyncio.run(coro)


def knowledge_base(page_size_seen=None):
    """A fake LightRAG holding DOCS, served 2 per page."""
    def handler(request):
        if request.url.path == "/documents/paginated":
            body = json.loads(request.content)
            if page_size_seen is not None:
                page_size_seen.append(body)
            page = body["page"]
            docs = DOCS[(page - 1) * 2: page * 2]
            return httpx.Response(200, json={
                "documents": docs, "status_counts": {"processed": 3, "failed": 1, "pending": 0, "all": 4},
                "pagination": {"page": page, "total_count": 4, "total_pages": 2, "has_next": page < 2}})
        if request.url.path == "/documents/delete_document" and request.method == "DELETE":
            ids = json.loads(request.content)["doc_ids"]
            return httpx.Response(200, json={"status": "deletion_started", "message": "ok", "doc_id": ", ".join(ids)})
        return httpx.Response(404)
    return handler


def test_list_sends_paging_and_status(fake_lightrag):
    seen = fake_lightrag(knowledge_base())
    run(lightrag.list_documents(Settings.from_env(), 2, 50, "failed"))
    body = json.loads(seen[0].content)
    assert body == {"page": 2, "page_size": 50, "sort_field": "created_at", "sort_direction": "desc",
                    "status_filters": ["failed"]}


def test_list_returns_only_what_an_agent_needs(fake_lightrag):
    fake_lightrag(knowledge_base())
    out = json.loads(run(lightrag.list_documents(Settings.from_env(), 1, 20, "")))
    assert out["status_counts"] == {"processed": 3, "failed": 1, "all": 4}          # zero counts dropped
    assert out["documents"][0] == {"id": "doc-aaa", "name": "monthly-report", "status": "processed",
                                   "created_at": "2026-10-18T04:33:14", "characters": 456,
                                   "summary": "# Monthly report 1. sales"}
    assert out["documents"][1]["error"] == "LLM timeout"


def test_delete_by_id_and_by_name(fake_lightrag):
    seen = fake_lightrag(knowledge_base())
    out = json.loads(run(lightrag.delete(Settings.from_env(), ["doc-aaa", "บันทึก-ประชุม"])))
    delete = [r for r in seen if r.method == "DELETE"][0]
    assert json.loads(delete.content)["doc_ids"] == ["doc-aaa", "doc-bbb"]
    assert out["requested"] == {"doc-aaa": "doc-aaa", "บันทึก-ประชุม": "doc-bbb"} and out["not_deleted"] == {}
    assert out["lightrag"]["status"] == "deletion_started"


def test_names_are_searched_on_every_page(fake_lightrag):
    seen = fake_lightrag(knowledge_base())
    out = json.loads(run(lightrag.delete(Settings.from_env(), ["twin", "missing"])))
    assert [json.loads(r.content)["page"] for r in seen if r.method == "POST"] == [1, 2]
    assert "doc-ccc" in out["not_deleted"]["twin"] and "doc-ddd" in out["not_deleted"]["twin"]   # ambiguous
    assert "no document" in out["not_deleted"]["missing"]
    assert not any(r.method == "DELETE" for r in seen)                    # nothing certain -> nothing deleted


def test_busy_lightrag_is_reported(fake_lightrag):
    fake_lightrag(lambda r: httpx.Response(200, json={"status": "busy", "message": "pipeline is busy"}))
    out = json.loads(run(lightrag.delete(Settings.from_env(), ["doc-aaa"])))
    assert out["lightrag"]["status"] == "busy"


# ------------------------------------------------------------------ through MCP


def test_delete_is_off_by_default(load_server):
    t = tools(load_server())
    assert "lightrag_delete" not in t and "lightrag_list_documents" in t
    assert t["lightrag_list_documents"]["annotations"]["readOnlyHint"] is True


def test_delete_can_be_switched_on_and_is_marked_destructive(load_server):
    t = tools(load_server(ENABLE_DELETE="true"))
    assert t["lightrag_delete"]["annotations"]["destructiveHint"] is True
    assert "กู้คืนไม่ได้" in t["lightrag_delete"]["description"]
    assert t["lightrag_delete"]["inputSchema"]["required"] == ["documents"]


def test_read_only_server_still_lists(load_server):
    assert set(tools(load_server(ENABLE_INSERT="false"))) == {"lightrag_query", "lightrag_list_documents"}


def test_delete_through_mcp(load_server, fake_lightrag):
    server = load_server(ENABLE_DELETE="true")
    fake_lightrag(knowledge_base())
    out = json.loads(call(server, "lightrag_delete", documents=["monthly-report"]))
    assert out["requested"] == {"monthly-report": "doc-aaa"}


@pytest.mark.parametrize("status,ok", [("failed", True), ("done", False)])
def test_list_status_is_checked(load_server, fake_lightrag, status, ok):
    server = load_server()
    seen = fake_lightrag(knowledge_base())
    out = call(server, "lightrag_list_documents", status=status)
    assert (len(seen) == 1) is ok and (out.startswith("[unknown status") is not ok)
