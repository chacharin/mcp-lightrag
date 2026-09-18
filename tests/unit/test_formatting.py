"""Unit tests for formatting.py's summarization helpers, independent of
any LightRAG mock/tool plumbing (see formatting.py's module docstring).

plan.md Phase 4.2 requires proving `get_pipeline_status` shrinks a ~30KB
raw response down to no more than 2KB -- test_pipeline_status_size below
asserts that literally, on a synthetic payload built to be >=30KB.
"""

from __future__ import annotations

import json

from mcp_lightrag.formatting import summarize_document, summarize_pipeline_status

# update_status maps every storage namespace to its own lock/busy state and
# is what makes a real pipeline_status response balloon to ~30KB on a busy
# instance with many namespaces -- reproduce that shape here rather than
# just a single big string, so this test tracks the real failure mode.
_RAW_PIPELINE = {
    "busy": True,
    "job_name": "Indexing files",
    "job_start": "2025-03-31T12:00:00+00:00",
    "docs": 5,
    "batchs": 2,
    "cur_batch": 1,
    "latest_message": "Processing chunk 3/10",
    "history_messages": [f"line {i}: doing some indexing work" for i in range(500)],
    "update_status": {
        f"namespace_{i}": {"locked": False, "holder": None, "queue_len": 0}
        for i in range(400)
    },
    "recovery_required": False,
    "recovery_kind": None,
    "recovery_message": None,
}


def test_raw_pipeline_fixture_is_at_least_30kb() -> None:
    """Sanity check on the fixture itself, so the real assertion below is
    testing something meaningful."""
    assert len(json.dumps(_RAW_PIPELINE)) >= 30_000


def test_summarize_pipeline_status_shrinks_30kb_response_to_2kb_or_less() -> None:
    summary = summarize_pipeline_status(_RAW_PIPELINE)

    assert len(json.dumps(summary)) <= 2_000
    assert "update_status" not in summary
    assert summary["busy"] is True
    assert summary["job_name"] == "Indexing files"


def test_summarize_pipeline_status_keeps_only_the_most_recent_history_lines() -> None:
    summary = summarize_pipeline_status(_RAW_PIPELINE)

    assert len(summary["history_messages"]) == 10
    assert summary["history_messages"][-1] == "line 499: doing some indexing work"


def test_summarize_pipeline_status_verbose_returns_the_full_payload_unchanged() -> None:
    summary = summarize_pipeline_status(_RAW_PIPELINE, verbose=True)

    assert summary is _RAW_PIPELINE
    assert "update_status" in summary
    assert len(summary["history_messages"]) == 500


def test_summarize_document_keeps_only_the_listed_fields() -> None:
    raw = {
        "id": "doc-1",
        "content_summary": "should be dropped",
        "content_length": 12345,
        "file_path": "joc-1.md",
        "status": "processed",
        "created_at": "2025-03-31T12:34:56",
        "updated_at": "2025-03-31T12:35:30",
        "track_id": "upload_123",
        "chunks_count": 12,
        "metadata": {"author": "someone"},
    }

    summary = summarize_document(raw)

    assert summary == {
        "id": "doc-1",
        "file_path": "joc-1.md",
        "status": "processed",
        "chunks_count": 12,
        "updated_at": "2025-03-31T12:35:30",
    }


def test_summarize_document_includes_error_msg_only_when_present() -> None:
    without_error = {"id": "doc-1", "file_path": "a.md", "status": "processed"}
    with_error = {
        "id": "doc-2",
        "file_path": "b.md",
        "status": "failed",
        "error_msg": "parse failed",
    }

    assert "error_msg" not in summarize_document(without_error)
    assert summarize_document(with_error)["error_msg"] == "parse failed"
