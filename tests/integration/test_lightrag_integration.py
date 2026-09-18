"""Phase 4.5 integration tests: exercise the real tool functions against a
real, running LightRAG instance -- never mocked.

DANGER: the full lifecycle test ends by calling `clear_all_documents`,
which deletes EVERY document the target instance holds. Per plan.md
section 4.5, only ever point this at a disposable test instance (e.g. a
second `docker compose -p knowledge-test up -d` on port 9622), never at
a real knowledge base.

Excluded from the default test run (pyproject.toml's
`addopts = "-m 'not integration'"`). Run explicitly with:

    # PowerShell, against a disposable instance on port 9622:
    $env:LIGHTRAG_URL="http://localhost:9622"
    $env:LIGHTRAG_API_KEY="<key, if the test instance has one>"
    uv run pytest tests/integration -m integration -v

Uses a short Thai-language document, per plan.md's "ใช้เอกสารสั้นเพื่อลด
ค่าใช้จ่าย OpenRouter" (use a short document to limit LLM cost), since
`query`/`query_data` and entity extraction on insert both call the real
LLM configured on the target LightRAG instance.
"""

from __future__ import annotations

from typing import Any

import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.documents import (
    clear_all_documents,
    delete_documents,
    get_document_status_counts,
    get_track_status,
    insert_text,
    list_documents,
)
from mcp_lightrag.tools.graph import (
    check_entity_exists,
    create_entity,
    delete_entity,
    edit_entity,
    search_labels,
)
from mcp_lightrag.tools.query import query, query_data
from mcp_lightrag.tools.system import health
from tests.integration.conftest import build_ctx, make_real_client, poll_until

pytestmark = pytest.mark.integration

# Deliberately does NOT mention _TEST_ENTITY_NAME: LightRAG's LLM extracts
# entities from indexed text automatically, so if the document's own
# content named the same entity this test creates by hand, create_entity
# would 400 with "already exists" against the auto-extracted one.
_TEST_TEXT = (
    "เอกสารทดสอบสำหรับ mcp-lightrag Phase 4.5: ระบบนี้ใช้ตรวจสอบการเชื่อมต่อ "
    "ระหว่าง Hermes Agent กับ LightRAG ให้ทำงานถูกต้อง"
)
_TEST_FILE_SOURCE = "mcp-lightrag-integration-test"
_TEST_ENTITY_NAME = "McpLightragPhase45ManualTestEntity"


async def test_health_check_reaches_the_target_instance() -> None:
    """Runs first and alone so a misconfigured LIGHTRAG_URL / API key fails
    fast with a clear message, instead of midway through the long
    lifecycle test below."""
    async with make_real_client() as client:
        ctx = build_ctx(client)
        result = await health(ctx)

    assert "document_status_counts" in result


async def test_full_document_and_graph_lifecycle() -> None:
    """The plan.md 4.5 flow, end to end:

    health -> insert_text -> poll get_track_status until processed ->
    list_documents finds it -> get_document_status_counts ->
    query (with references) -> query_data -> search_labels ->
    create/edit/delete entity -> delete_documents -> clear_all_documents ->
    list_documents is empty.
    """
    async with make_real_client() as client:
        ctx = build_ctx(client)

        # health
        await health(ctx)

        # Start from a known-empty state: a previous run that failed partway
        # through (before reaching this test's own clear_all_documents at the
        # end) can leave the test document behind, and LightRAG rejects
        # re-inserting the same file_source with 409 Conflict. Safe here
        # specifically because this test only ever targets a disposable test
        # instance (see the module docstring's DANGER note) -- never the
        # real knowledge base.
        await clear_all_documents(ctx)

        # clear_all_documents only clears the document store -- the graph
        # store (entities/relations) is separate and survives it, so also
        # clean up a leftover test entity from any previous partial run.
        try:
            await delete_entity(ctx, entity_name=_TEST_ENTITY_NAME)
        except LightRAGError as exc:
            if exc.status_code != 404:
                raise

        # insert_text
        inserted = await insert_text(
            ctx, text=_TEST_TEXT, file_source=_TEST_FILE_SOURCE
        )
        track_id = inserted.get("track_id") or inserted.get("id")
        assert track_id, f"insert_text did not return a track_id: {inserted}"

        # poll get_track_status until processed (or failed, which fails the test)
        async def _check_processed() -> dict[str, Any] | None:
            status = await get_track_status(ctx, track_id=track_id)
            documents = status.get("documents") or []
            if not documents:
                return None
            doc = documents[0]
            if doc.get("status") == "failed":
                raise AssertionError(f"Document processing failed: {doc}")
            if doc.get("status") == "processed":
                return status
            return None

        track_status = await poll_until(
            _check_processed,
            timeout=180.0,
            interval=3.0,
            description="get_track_status to report status=processed",
        )
        doc_id = track_status["documents"][0]["id"]

        # list_documents finds it
        listed = await list_documents(ctx, page_size=200)
        assert any(doc["id"] == doc_id for doc in listed["documents"]), (
            f"Inserted document {doc_id} not found in list_documents: {listed}"
        )

        # get_document_status_counts -- real shape is {"status_counts": {...}},
        # per tests/unit/tools/test_documents.py's own fixture
        counts = await get_document_status_counts(ctx)
        assert counts["status_counts"].get("processed", 0) >= 1

        # query -- must come back with references, since include_references
        # defaults to True (plan.md section 3's "Hermes ไม่พบเอกสาร" fix)
        answer = await query(
            ctx, query="ระบบนี้ใช้ตรวจสอบการเชื่อมต่อระหว่างอะไร", mode="hybrid"
        )
        assert answer.get("response")
        assert answer.get("references"), f"query returned no references: {answer}"

        # query_data -- raw retrieval, no LLM answer generation
        data = await query_data(ctx, query="Hermes Agent LightRAG", mode="hybrid")
        assert isinstance(data, dict)

        # search_labels -- just needs to succeed; entity extraction from a
        # short document is not guaranteed to name any particular label
        labels = await search_labels(ctx, q="Hermes")
        assert isinstance(labels, list)

        # create / check / edit / delete entity
        await create_entity(
            ctx,
            entity_name=_TEST_ENTITY_NAME,
            entity_data={
                "description": "Created by mcp-lightrag Phase 4.5 integration test",
                "entity_type": "TEST",
            },
        )
        exists = await check_entity_exists(ctx, name=_TEST_ENTITY_NAME)
        assert exists.get("exists") is True

        await edit_entity(
            ctx,
            entity_name=_TEST_ENTITY_NAME,
            updated_data={"description": "Updated by integration test"},
        )
        await delete_entity(ctx, entity_name=_TEST_ENTITY_NAME)
        exists_after_delete = await check_entity_exists(ctx, name=_TEST_ENTITY_NAME)
        assert exists_after_delete.get("exists") is False

        # delete_documents -- runs in the background; poll until gone
        await delete_documents(ctx, doc_ids=[doc_id], delete_file=False)

        async def _check_deleted() -> bool | None:
            listed_after = await list_documents(ctx, page_size=200)
            still_present = any(
                doc["id"] == doc_id for doc in listed_after["documents"]
            )
            return True if not still_present else None

        await poll_until(
            _check_deleted,
            timeout=60.0,
            interval=2.0,
            description="deleted document to disappear from list_documents",
        )

        # clear_all_documents -- final cleanup so the disposable test
        # instance ends this run empty, per plan.md's own exit condition
        await clear_all_documents(ctx)

        async def _check_empty() -> bool | None:
            listed_final = await list_documents(ctx, page_size=200)
            return True if not listed_final["documents"] else None

        await poll_until(
            _check_empty,
            timeout=60.0,
            interval=2.0,
            description="list_documents to be empty after clear_all_documents",
        )
