"""Response-shaping helpers shared by tools/*.py.

Kept separate from the tools themselves so the summarization logic (which
is what actually fixes the "30KB pipeline status dump" problem the old
wrapper had) has its own focused unit tests, independent of any LightRAG
mock plumbing.
"""

from __future__ import annotations

from typing import Any

#: How many of the most recent pipeline history lines to keep in the
#: non-verbose summary. LightRAG's own history can run into the hundreds of
#: lines on a long-running instance; 10 is enough to see what a job is
#: currently doing without shipping the whole log to the agent's context.
_HISTORY_TAIL = 10

# update_status maps every storage namespace to its own busy/lock state and
# is the single largest field in a raw pipeline_status response -- it is
# operational detail an agent asking "what is LightRAG doing right now"
# never needs, so it is the one field dropped even when everything else is
# kept.
_PIPELINE_SUMMARY_FIELDS = (
    "busy",
    "job_name",
    "job_start",
    "docs",
    "batchs",
    "cur_batch",
    "latest_message",
    "recovery_required",
    "recovery_kind",
    "recovery_message",
)


def summarize_pipeline_status(
    data: dict[str, Any], *, verbose: bool = False
) -> dict[str, Any]:
    """Condense a `GET /documents/pipeline_status` response.

    `verbose=True` returns `data` unchanged (the full response, which can
    run to ~30KB on a busy instance with a long update_status map).
    Otherwise, returns just the fields that answer "what is the pipeline
    doing right now", with `history_messages` cut to the most recent
    `_HISTORY_TAIL` entries.
    """
    if verbose:
        return data

    summary = {field: data.get(field) for field in _PIPELINE_SUMMARY_FIELDS}
    history = data.get("history_messages") or []
    summary["history_messages"] = list(history[-_HISTORY_TAIL:])
    return summary


#: Fields kept from a raw LightRAG document-status object, per plan.md
#: section 4.2: "id, file_path, status, chunks_count, updated_at, error_msg
#: ถ้ามี" -- everything else (content_summary, content_length, metadata,
#: track_id, created_at) is dropped to keep a page of results small.
_DOCUMENT_SUMMARY_FIELDS = ("id", "file_path", "status", "chunks_count", "updated_at")


def summarize_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Shrink one raw document-status object to the fields list_documents
    needs. `error_msg` is included only when the document actually has one,
    per plan.md's "error_msg ถ้ามี" (error_msg, if present).
    """
    summary = {field: doc.get(field) for field in _DOCUMENT_SUMMARY_FIELDS}
    error_msg = doc.get("error_msg")
    if error_msg:
        summary["error_msg"] = error_msg
    return summary
