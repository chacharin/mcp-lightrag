"""Calls to the LightRAG server REST API: POST /query, POST /documents/text, POST /documents/paginated,
DELETE /documents/delete_document and the /health checks.

Every failure comes back as a short text that tells the agent (and the person reading its log)
what went wrong; nothing here raises to the MCP layer.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import httpx

from app.config import Settings

# tests replace this with an httpx.MockTransport; None = real network
transport: httpx.AsyncBaseTransport | None = None

# document states of LightRAG 1.5 ("preprocessed" is deprecated there)
DOC_STATUSES = ("processed", "pending", "parsing", "analyzing", "processing", "failed")

# characters that would make an awkward document name in LightRAG (Thai vowel marks are kept)
_UNSAFE_NAME = re.compile(r'[\s/\\:*?"<>|]+')
_KEY_HINT = " - check LIGHTRAG_API_KEY (it must match the key set on the LightRAG server)"


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport)


def _headers(S: Settings) -> dict:
    return {"X-API-Key": S.lightrag_api_key}


def _http_error(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    hint = _KEY_HINT if code in (401, 403) else ""
    return f"[LightRAG error HTTP {code}{hint}]: {e.response.text[:500]}"


def _connection_error(e: httpx.HTTPError, S: Settings) -> str:
    return f"[LightRAG connection error: {type(e).__name__} - cannot reach LIGHTRAG_URL {S.lightrag_url}]"


def format_answer(data) -> str:
    """LightRAG answers {"response": "...", "references": [{"reference_id", "file_path"}, ...]}:
    return the answer text, followed by the documents retrieved for it - unless the answer already
    cites any of them, as LightRAG's default prompt asks the LLM to (it cites only those it used)."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict) and isinstance(data.get("response"), str):
        text = data["response"]
        refs = [r for r in data.get("references") or [] if isinstance(r, dict) and r.get("file_path")]
        if refs and not any(r["file_path"] in text for r in refs):
            text += "\n\nReferences:\n" + "\n".join(f"- [{r.get('reference_id', '?')}] {r['file_path']}" for r in refs)
        return text
    return json.dumps(data, ensure_ascii=False)


def document_name(description: str, now: dt.datetime | None = None) -> str:
    """The file_source LightRAG stores the text under: the description made path-safe,
    or insert-<date>-<time> when there is none."""
    name = _UNSAFE_NAME.sub("-", (description or "").strip()).strip("-")[:80]
    return name or f"insert-{(now or dt.datetime.now()):%Y%m%d-%H%M%S}"


async def query(S: Settings, question: str, mode: str) -> str:
    body = {**S.query_extra_params, "query": question, "mode": mode, "stream": False}
    try:
        async with _client(S.query_timeout) as c:
            r = await c.post(f"{S.lightrag_url}/query", json=body, headers=_headers(S))
        r.raise_for_status()
        return format_answer(r.json())
    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except httpx.HTTPError as e:
        return _connection_error(e, S)
    except ValueError:                       # 200 but not JSON
        return r.text[:4000]


async def insert(S: Settings, text: str, description: str) -> str:
    name = document_name(description)
    try:
        async with _client(S.insert_timeout) as c:
            r = await c.post(f"{S.lightrag_url}/documents/text", json={"text": text, "file_source": name},
                             headers=_headers(S))
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except httpx.HTTPError as e:
        return _connection_error(e, S)
    except ValueError:
        return r.text[:4000]
    # LightRAG indexes the text in the background; status "success" means it was accepted
    if isinstance(data, dict):
        data = {**data, "file_source": name}
    return json.dumps(data, ensure_ascii=False)


def _doc_row(d: dict) -> dict:
    """The fields an agent needs to pick a document, without LightRAG's processing metadata."""
    row = {"id": d.get("id"), "name": d.get("file_path"), "status": d.get("status"),
           "created_at": (d.get("created_at") or "")[:19], "characters": d.get("content_length"),
           "summary": " ".join((d.get("content_summary") or "").split())[:120]}
    if d.get("error_msg"):
        row["error"] = d["error_msg"]
    return row


async def _page(c: httpx.AsyncClient, S: Settings, page: int, page_size: int, status: str = "") -> dict:
    body: dict = {"page": page, "page_size": page_size, "sort_field": "created_at", "sort_direction": "desc"}
    if status:
        body["status_filters"] = [status]
    r = await c.post(f"{S.lightrag_url}/documents/paginated", json=body, headers=_headers(S))
    r.raise_for_status()
    return r.json()


async def list_documents(S: Settings, page: int, page_size: int, status: str) -> str:
    try:
        async with _client(S.insert_timeout) as c:
            data = await _page(c, S, page, page_size, status)
    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except httpx.HTTPError as e:
        return _connection_error(e, S)
    counts = {k: v for k, v in (data.get("status_counts") or {}).items() if v}
    return json.dumps({"pagination": data.get("pagination"), "status_counts": counts,
                       "documents": [_doc_row(d) for d in data.get("documents") or []]}, ensure_ascii=False)


async def _resolve(c: httpx.AsyncClient, S: Settings, wanted: list[str]) -> tuple[dict, dict]:
    """Map each wanted item (a doc-… id or a document name) to an id.
    Returns ({item: id}, {item: why it cannot be deleted})."""
    ids = {w: w for w in wanted if w.startswith("doc-")}
    names = [w for w in wanted if w not in ids]
    found: dict[str, list[str]] = {n: [] for n in names}
    if names:
        page = 1
        while page <= 50:                                  # at most 10,000 documents are searched
            data = await _page(c, S, page, 200)
            for d in data.get("documents") or []:
                if d.get("file_path") in found:
                    found[d["file_path"]].append(d["id"])
            if not (data.get("pagination") or {}).get("has_next"):
                break
            page += 1
    problems = {}
    for n, hits in found.items():
        if len(hits) == 1:
            ids[n] = hits[0]
        else:
            problems[n] = ("no document has this name or id" if not hits
                           else f"{len(hits)} documents share this name - delete by id: {', '.join(hits)}")
    return ids, problems


async def delete(S: Settings, documents: list[str]) -> str:
    wanted = list(dict.fromkeys(d.strip() for d in documents if d and d.strip()))
    try:
        async with _client(S.insert_timeout) as c:
            ids, problems = await _resolve(c, S, wanted)
            if not ids:
                return json.dumps({"requested": {}, "not_deleted": problems}, ensure_ascii=False)
            r = await c.request("DELETE", f"{S.lightrag_url}/documents/delete_document",
                                json={"doc_ids": list(dict.fromkeys(ids.values()))}, headers=_headers(S))
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except httpx.HTTPError as e:
        return _connection_error(e, S)
    except ValueError:
        return r.text[:4000]
    # "deletion_started" = LightRAG removes the text, chunks and graph data in the background;
    # "busy" = it is indexing or deleting something else - nothing was deleted, try again later
    return json.dumps({"lightrag": data, "requested": ids, "not_deleted": problems}, ensure_ascii=False)


async def check(S: Settings) -> dict:
    """Is LightRAG reachable, and does it accept our key? (/health is public on a default LightRAG
    server, so the key is checked on /documents/pipeline_status, which needs it.)"""
    out: dict = {"reachable": False, "key_accepted": None}
    try:
        async with _client(5) as c:
            r = await c.get(f"{S.lightrag_url}/health", headers=_headers(S))
            out["reachable"] = r.status_code == 200
            out["http_status"] = r.status_code
            if out["reachable"]:
                k = await c.get(f"{S.lightrag_url}/documents/pipeline_status", headers=_headers(S))
                if k.status_code in (401, 403):
                    out["key_accepted"] = False
                elif k.status_code == 200:
                    out["key_accepted"] = True
    except httpx.HTTPError as e:
        out["detail"] = type(e).__name__
    return out
