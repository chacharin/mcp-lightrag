"""Document tools (plan.md section 4.2).

Round 3A (read-only): list_documents, get_document_status_counts,
get_pipeline_status, get_track_status, get_supported_file_types,
get_scan_status, list_source_conflicts.

Round 3B (add/edit): insert_text, insert_texts, upload_file,
upload_directory, scan_documents, reprocess_failed_documents.

Round 3C (delete/pipeline control): delete_documents,
clear_all_documents, force_reset_recovery, cancel_pipeline,
repair_source_conflict.

Every tool function here is a plain top-level async function so
tests/unit/tools/test_documents.py can import and call it directly with a
fake ctx. `register()` is the only thing server.py calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from mcp_lightrag.formatting import summarize_document, summarize_pipeline_status
from mcp_lightrag.tools._common import get_client

if TYPE_CHECKING:
    from mcp_lightrag.client import LightRAGClient

DocStatusFilter = Literal[
    "pending",
    "parsing",
    "analyzing",
    "processing",
    "preprocessed",
    "processed",
    "failed",
]

_STATUS_FILTER_DESC = (
    "Only return documents in this status. Omit to return documents in every status."
)
_PAGE_DESC = "Page number, 1-based."
_PAGE_SIZE_DESC = "Documents per page (10-200)."
_SORT_FIELD_DESC = "Field to sort by."
_SORT_DIRECTION_DESC = "Sort direction."


async def list_documents(
    ctx: Context[Any, Any],
    status_filter: Annotated[
        DocStatusFilter | None, Field(description=_STATUS_FILTER_DESC)
    ] = None,
    page: Annotated[int, Field(description=_PAGE_DESC, ge=1)] = 1,
    page_size: Annotated[int, Field(description=_PAGE_SIZE_DESC, ge=10, le=200)] = 50,
    sort_field: Annotated[
        Literal["created_at", "updated_at", "id", "file_path"],
        Field(description=_SORT_FIELD_DESC),
    ] = "updated_at",
    sort_direction: Annotated[
        Literal["asc", "desc"], Field(description=_SORT_DIRECTION_DESC)
    ] = "desc",
) -> dict[str, Any]:
    """List documents in the knowledge base, with pagination. This is the
    tool to use for "how many documents are there" or "list the documents"
    -- do not conclude the knowledge base is empty from a tool failure;
    that means LightRAG could not be reached, not that there are zero
    documents (this is the exact bug this server exists to fix). Returns a
    trimmed per-document summary (id, file_path, status, chunks_count,
    updated_at, error_msg if any) plus total_count and has_next."""
    client = get_client(ctx)
    body: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
        "sort_field": sort_field,
        "sort_direction": sort_direction,
    }
    if status_filter is not None:
        body["status_filter"] = status_filter
    raw = await client.request("POST", "/documents/paginated", json=body)
    pagination = raw.get("pagination", {})
    return {
        "documents": [summarize_document(doc) for doc in raw.get("documents", [])],
        "total_count": pagination.get("total_count"),
        "has_next": pagination.get("has_next"),
        "page": pagination.get("page"),
        "page_size": pagination.get("page_size"),
    }


async def get_document_status_counts(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Get the count of documents in each processing status (pending,
    processing, processed, failed, ...). The fast, low-context way to
    answer "how many documents does LightRAG have" -- prefer this over
    `list_documents` when only the counts are needed."""
    client = get_client(ctx)
    return await client.request("GET", "/documents/status_counts")


async def get_pipeline_status(
    ctx: Context[Any, Any],
    verbose: Annotated[
        bool,
        Field(
            description=(
                "Return the full raw pipeline status (can be tens of "
                "kilobytes on a busy instance) instead of the condensed "
                "summary."
            )
        ),
    ] = False,
) -> dict[str, Any]:
    """Check what LightRAG's indexing pipeline is doing right now: busy or
    idle, current job name and progress, and the most recent status
    messages. Use this for "what is LightRAG processing" -- by default
    returns a short summary (the last 10 history lines), not the full
    internal state; pass verbose=true only if the summary is not enough."""
    client = get_client(ctx)
    raw = await client.request("GET", "/documents/pipeline_status")
    return summarize_pipeline_status(raw, verbose=verbose)


async def get_track_status(
    ctx: Context[Any, Any],
    track_id: Annotated[
        str,
        Field(
            description="Tracking ID returned by insert_text, insert_texts, upload_file, or scan_documents."
        ),
    ],
) -> dict[str, Any]:
    """Check the processing status of the document(s) associated with a
    track_id -- use this after insert_text/insert_texts/upload_file to see
    whether indexing finished, and whether it succeeded."""
    client = get_client(ctx)
    raw = await client.request("GET", f"/documents/track_status/{track_id}")
    return {
        "track_id": raw.get("track_id"),
        "documents": [summarize_document(doc) for doc in raw.get("documents", [])],
        "total_count": raw.get("total_count"),
        "status_summary": raw.get("status_summary"),
    }


async def get_supported_file_types(ctx: Context[Any, Any]) -> dict[str, Any]:
    """List the file extensions LightRAG accepts for upload, and which
    parser engine handles each. Check this before `upload_file` if the
    file's extension is not obviously supported."""
    client = get_client(ctx)
    return await client.request("GET", "/documents/supported_file_types")


async def get_scan_status(
    ctx: Context[Any, Any],
    track_id: Annotated[
        str, Field(description="Tracking ID returned by scan_documents.")
    ],
) -> dict[str, Any]:
    """Check the progress of a background folder scan started by
    `scan_documents`."""
    client = get_client(ctx)
    return await client.request("GET", f"/documents/scan/status/{track_id}")


async def list_source_conflicts(
    ctx: Context[Any, Any],
    limit: Annotated[
        int,
        Field(description="Maximum conflicts to return in this page.", ge=1, le=200),
    ] = 50,
    cursor: Annotated[
        str | None,
        Field(
            description="Opaque next_cursor from a previous call, to fetch the next page."
        ),
    ] = None,
) -> dict[str, Any]:
    """List documents whose source file name collides with another
    document's (a "source conflict") -- these were never auto-resolved
    because picking a winner automatically could retire the wrong
    document. Use `repair_source_conflict` to resolve one."""
    client = get_client(ctx)
    params: dict[str, Any] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor
    return await client.request("GET", "/documents/source_conflicts", params=params)


async def insert_text(
    ctx: Context[Any, Any],
    text: Annotated[
        str,
        Field(
            description="The text content to add to the knowledge base. Must not be empty."
        ),
    ],
    file_source: Annotated[
        str | None,
        Field(
            description="Name to attribute this text to in references, e.g. 'meeting-notes-2026-09-17'. Always set this so query() references can name where an answer came from."
        ),
    ] = None,
) -> dict[str, Any]:
    """Insert a single piece of raw text into the knowledge base for
    indexing. Returns a track_id -- poll with get_track_status to see when
    indexing finishes."""
    client = get_client(ctx)
    body: dict[str, Any] = {"text": text}
    if file_source is not None:
        body["file_source"] = file_source
    return await client.request("POST", "/documents/text", json=body)


async def insert_texts(
    ctx: Context[Any, Any],
    texts: Annotated[
        list[str],
        Field(
            description="The text contents to add to the knowledge base. None may be empty."
        ),
    ],
    file_sources: Annotated[
        list[str] | None,
        Field(
            description="Source name for each text, in the same order as texts. Always set this so query() references can name where an answer came from."
        ),
    ] = None,
) -> dict[str, Any]:
    """Insert multiple pieces of raw text into the knowledge base in one
    call. Returns a single track_id covering the whole batch -- poll with
    get_track_status."""
    client = get_client(ctx)
    body: dict[str, Any] = {"texts": texts}
    if file_sources is not None:
        body["file_sources"] = file_sources
    return await client.request("POST", "/documents/texts", json=body)


async def _fetch_supported_extensions(client: LightRAGClient) -> set[str]:
    supported = await client.request("GET", "/documents/supported_file_types")
    return {ext.lower() for ext in supported.get("supported_extensions", [])}


async def _upload_one(
    client: LightRAGClient, file_path: str, supported_extensions: set[str]
) -> dict[str, Any]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.suffix.lower() not in supported_extensions:
        raise ValueError(
            f"Unsupported file extension {path.suffix!r} for {file_path}; "
            f"supported extensions: {', '.join(sorted(supported_extensions))}"
        )
    data = await asyncio.to_thread(path.read_bytes)
    return await client.request(
        "POST",
        "/documents/upload",
        files={"file": (path.name, data)},
        timeout=client.upload_timeout,
    )


_UPLOAD_PATH_DESC = (
    "Absolute path to the file, as seen INSIDE the Hermes container -- NOT "
    "the Windows host path. E.g. a file at D:\\Harness\\workspace\\a.pdf on "
    "the host is /opt/data/workspace/a.pdf here."
)


async def upload_file(
    ctx: Context[Any, Any],
    path: Annotated[str, Field(description=_UPLOAD_PATH_DESC)],
) -> dict[str, Any]:
    """Upload and index a single file already present on disk. Checks the
    file exists and its extension is supported before uploading -- call
    get_supported_file_types first if unsure. Returns a track_id; poll
    with get_track_status."""
    client = get_client(ctx)
    if not Path(path).is_file():
        raise FileNotFoundError(f"File not found: {path}")
    extensions = await _fetch_supported_extensions(client)
    return await _upload_one(client, path, extensions)


async def upload_directory(
    ctx: Context[Any, Any],
    directory: Annotated[
        str,
        Field(
            description="Absolute path to a directory, as seen INSIDE the Hermes container, whose supported files should all be uploaded."
        ),
    ],
) -> dict[str, Any]:
    """Upload every supported file directly inside a directory, one by
    one, reporting each file's own outcome -- unsupported extensions are
    skipped (not treated as errors), and one file failing does not stop
    the rest. Use this instead of calling upload_file in a loop."""
    client = get_client(ctx)
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Directory not found: {directory}")
    extensions = await _fetch_supported_extensions(client)

    results: list[dict[str, Any]] = []
    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in extensions:
            results.append(
                {
                    "file": str(entry),
                    "status": "skipped",
                    "reason": "unsupported extension",
                }
            )
            continue
        try:
            outcome = await _upload_one(client, str(entry), extensions)
        except Exception as exc:  # noqa: BLE001 - reported per-file, not raised
            results.append({"file": str(entry), "status": "error", "error": str(exc)})
        else:
            results.append(
                {
                    "file": str(entry),
                    "status": outcome.get("status"),
                    "track_id": outcome.get("track_id"),
                    "message": outcome.get("message"),
                }
            )

    return {
        "results": results,
        "uploaded": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "error"),
    }


async def scan_documents(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Trigger a background scan of LightRAG's input directory for new
    files not yet indexed. Returns a track_id; poll with get_scan_status.
    Refuses with status='scanning_skipped_pipeline_busy' if a scan or the
    indexing pipeline is already running."""
    client = get_client(ctx)
    return await client.request("POST", "/documents/scan")


async def reprocess_failed_documents(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Retry documents currently in a failed, pending, or interrupted
    state, without rescanning the input directory for new files."""
    client = get_client(ctx)
    return await client.request("POST", "/documents/reprocess_failed")


async def delete_documents(
    ctx: Context[Any, Any],
    doc_ids: Annotated[
        list[str], Field(description="IDs of the documents to delete.", min_length=1)
    ],
    delete_file: Annotated[
        bool,
        Field(
            description="Also delete the corresponding file from the upload directory."
        ),
    ] = False,
    delete_llm_cache: Annotated[
        bool,
        Field(
            description="Also delete cached LLM extraction results for these documents."
        ),
    ] = False,
) -> dict[str, Any]:
    """DESTRUCTIVE: permanently deletes documents and all their associated
    data (status, text chunks, vector embeddings, related graph data).
    This cannot be undone. Runs in the background; use get_track_status or
    list_documents afterward to confirm."""
    client = get_client(ctx)
    return await client.request(
        "DELETE",
        "/documents/delete_document",
        json={
            "doc_ids": doc_ids,
            "delete_file": delete_file,
            "delete_llm_cache": delete_llm_cache,
        },
    )


async def clear_all_documents(
    ctx: Context[Any, Any],
    delete_parsed_files: Annotated[
        bool,
        Field(
            description="Also delete parsed-artifact files. Off by default so they survive re-adding the same documents later."
        ),
    ] = False,
    clear_llm_cache: Annotated[
        bool,
        Field(
            description="Also drop the entire LLM response cache. Off by default so re-adding the same documents can reuse already-paid-for extraction results."
        ),
    ] = False,
) -> dict[str, Any]:
    """DESTRUCTIVE: permanently deletes EVERY document in the knowledge
    base. This cannot be undone -- confirm with the user before calling
    this."""
    client = get_client(ctx)
    return await client.request(
        "DELETE",
        "/documents",
        params={
            "delete_parsed_files": delete_parsed_files,
            "clear_llm_cache": clear_llm_cache,
        },
    )


async def force_reset_recovery(
    ctx: Context[Any, Any],
    confirm: Annotated[
        bool,
        Field(
            description="Must be true to actually reset. The workspace may be in a partially-committed state; only set this after verifying/repairing it."
        ),
    ] = False,
) -> dict[str, Any]:
    """DESTRUCTIVE: force-clears a 'recovery_required' fence that blocks
    every mutation after a worker died mid-operation. This reopens a
    possibly-inconsistent workspace and cannot be undone -- use only to
    recover a stuck pipeline, and only after checking get_pipeline_status
    first. No-ops (status='no_recovery_required') if nothing is fenced."""
    client = get_client(ctx)
    return await client.request(
        "POST", "/documents/recovery/force_reset", json={"confirm": confirm}
    )


async def cancel_pipeline(ctx: Context[Any, Any]) -> dict[str, Any]:
    """Request cancellation of the currently-running indexing pipeline job.
    Documents already in progress will be marked FAILED. Use
    get_pipeline_status first to see what would be cancelled; returns
    status='not_busy' if nothing is running."""
    client = get_client(ctx)
    return await client.request("POST", "/documents/cancel_pipeline")


async def repair_source_conflict(
    ctx: Context[Any, Any],
    canonical_source_key: Annotated[
        str,
        Field(
            description="The conflict's canonical_source_key, from list_source_conflicts."
        ),
    ],
    primary_doc_id: Annotated[
        str,
        Field(
            description="Document ID from that conflict's sample_doc_ids to keep as the single primary."
        ),
    ],
    dry_run: Annotated[
        bool,
        Field(
            description=(
                "True (the default): report only, changes nothing, and returns the "
                "candidate_count/fingerprint pair to echo back for the real commit. "
                "False: commit the repair -- requires expected_candidate_count and "
                "expected_candidate_fingerprint from a prior dry-run, and fails if the "
                "candidate set changed since then."
            )
        ),
    ] = True,
    expected_candidate_count: Annotated[
        int | None,
        Field(
            description="candidate_count echoed from the dry-run. Required when dry_run is false."
        ),
    ] = None,
    expected_candidate_fingerprint: Annotated[
        str | None,
        Field(
            description="fingerprint echoed from the dry-run. Required when dry_run is false."
        ),
    ] = None,
) -> dict[str, Any]:
    """Resolve a source-name conflict (from list_source_conflicts) by
    naming one document as the primary. Always dry_run first to see what
    would change; committing (dry_run=false) marks the other candidates as
    duplicates -- their content is not deleted, but this still cannot be
    trivially undone, so double-check the dry-run result first."""
    client = get_client(ctx)
    body: dict[str, Any] = {
        "canonical_source_key": canonical_source_key,
        "primary_doc_id": primary_doc_id,
        "dry_run": dry_run,
    }
    if expected_candidate_count is not None:
        body["expected_candidate_count"] = expected_candidate_count
    if expected_candidate_fingerprint is not None:
        body["expected_candidate_fingerprint"] = expected_candidate_fingerprint
    return await client.request("POST", "/documents/source_conflicts/repair", json=body)


def register(server: MCPServer[Any]) -> None:
    server.add_tool(list_documents)
    server.add_tool(get_document_status_counts)
    server.add_tool(get_pipeline_status)
    server.add_tool(get_track_status)
    server.add_tool(get_supported_file_types)
    server.add_tool(get_scan_status)
    server.add_tool(list_source_conflicts)
    server.add_tool(insert_text)
    server.add_tool(insert_texts)
    server.add_tool(upload_file)
    server.add_tool(upload_directory)
    server.add_tool(scan_documents)
    server.add_tool(reprocess_failed_documents)
    server.add_tool(delete_documents)
    server.add_tool(clear_all_documents)
    server.add_tool(force_reset_recovery)
    server.add_tool(cancel_pipeline)
    server.add_tool(repair_source_conflict)
