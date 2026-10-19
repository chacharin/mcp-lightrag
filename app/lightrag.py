"""Calls to the LightRAG server REST API: POST /query, POST /documents/text and the /health checks.

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

# characters that would make an awkward document name in LightRAG (Thai vowel marks are kept)
_UNSAFE_NAME = re.compile(r'[\s/\\:*?"<>|]+')
_KEY_HINT = " - check LIGHTRAG_API_KEY (it must match the key set on the LightRAG server)"


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=transport)


def _headers(S: Settings) -> dict:
    return {"X-API-Key": S.lightrag_api_key} if S.lightrag_api_key else {}


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
