"""LLM meter: an optional pass-through for the LightRAG server's own model calls, so their tokens are logged.

LightRAG calls an LLM (keyword extraction, the answer) and an embedding model for every query and every
inserted document, but reports no token usage. Point the LightRAG server at this meter instead of the
provider (LLM_BINDING_HOST / EMBEDDING_BINDING_HOST = http://mcp-lightrag:8700/meter/v1) and every call
is forwarded unchanged to METER_UPSTREAM, with one usage record per call (component "lightrag").

The meter keeps no key: LightRAG's own Authorization header is passed through. Only METER_UPSTREAM can be
reached, so the meter is not an open proxy. Empty METER_UPSTREAM = the meter is off (404).
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.usage import UsageLog, openai_usage

# tests replace this with an httpx.MockTransport; None = real network
transport: httpx.AsyncBaseTransport | None = None
PASS_HEADERS = ("authorization", "content-type", "accept", "http-referer", "x-title", "user-agent")


def _kind(path: str) -> str:
    return "embedding_call" if path.rstrip("/").endswith("embeddings") else "llm_call"


def _record(log: UsageLog, path: str, body: Any, t0: float, first: float | None, status: int,
            data: dict | None, request_chars: int, response_chars: int, error: str | None) -> None:
    t1 = time.time()
    tokens = openai_usage(data or {})
    kind = _kind(path)
    if kind == "embedding_call" and tokens.get("input_tokens") is not None:
        tokens["output_tokens"] = 0
    out = tokens.get("output_tokens")
    gen = (t1 - first) if first else (t1 - t0)
    inputs = body.get("input") if isinstance(body, dict) else None
    log.write({"kind": kind, "component": "lightrag", "tool": "lightrag-server",
               "model": (data or {}).get("model") or (body.get("model") if isinstance(body, dict) else None),
               "upstream_provider": (data or {}).get("provider"), "endpoint_host": path,
               "started_at": round(t0, 3), "ended_at": round(t1, 3), "duration_s": round(t1 - t0, 3),
               "ttfb_s": round(first - t0, 3) if first else None, **tokens,
               "output_tps": round(out / gen, 2) if out and gen > 0 else None,
               "status": "ok" if status < 400 and not error else "error",
               "error": error or (f"HTTP {status}" if status >= 400 else None),
               "finish_reason": (((data or {}).get("choices") or [{}])[0] or {}).get("finish_reason"),
               "detail": {"via": "meter", "http_status": status, "request_chars": request_chars,
                          "response_chars": response_chars,
                          "inputs": len(inputs) if isinstance(inputs, list) else (1 if inputs else None),
                          "stream": bool(isinstance(body, dict) and body.get("stream"))}})


def _usage_from_sse(text: str) -> dict | None:
    """model, provider, usage and finish_reason of a streamed answer (usage comes in the final chunk)."""
    found: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
            continue
        try:
            d = json.loads(line[5:])
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        found.update({k: d[k] for k in ("model", "provider", "usage") if d.get(k)})
        fr = ((d.get("choices") or [{}])[0] or {}).get("finish_reason")
        if fr:
            found["choices"] = [{"finish_reason": fr}]
    return found or None


def make_endpoint(upstream: str, timeout: float, log: UsageLog):
    upstream = upstream.rstrip("/")

    async def endpoint(request: Request) -> Response:
        if not upstream:
            return JSONResponse({"error": "the LLM meter is off - set METER_UPSTREAM"}, status_code=404)
        path = request.path_params.get("path", "")
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        headers = {k: v for k, v in request.headers.items() if k.lower() in PASS_HEADERS}
        url = f"{upstream}/{path}" + (f"?{request.url.query}" if request.url.query else "")
        client = httpx.AsyncClient(timeout=timeout, transport=transport)
        t0 = time.time()
        try:
            req = client.build_request(request.method, url, content=raw, headers=headers)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            await client.aclose()
            _record(log, path, body, t0, None, 502, None, len(raw), 0, type(e).__name__)
            return JSONResponse({"error": f"meter: cannot reach METER_UPSTREAM ({type(e).__name__})"}, status_code=502)
        ctype = resp.headers.get("content-type", "")
        out_headers = {"content-type": ctype} if ctype else {}

        if "text/event-stream" in ctype:
            async def relay():
                first, chunks = None, []
                try:
                    async for chunk in resp.aiter_bytes():   # decoded: content-encoding is not passed on
                        if first is None:
                            first = time.time()
                        chunks.append(chunk)
                        yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()
                    text = b"".join(chunks).decode("utf-8", "replace")
                    _record(log, path, body, t0, first, resp.status_code, _usage_from_sse(text), len(raw),
                            len(text), None)
            return StreamingResponse(relay(), status_code=resp.status_code, headers=out_headers)

        data_bytes = await resp.aread()     # not streamed: no first-token time, the whole call is one wait
        await resp.aclose()
        await client.aclose()
        try:
            data = json.loads(data_bytes)
        except ValueError:
            data = None
        _record(log, path, body, t0, None, resp.status_code,
                data if isinstance(data, dict) else None, len(raw), len(data_bytes), None)
        return Response(data_bytes, status_code=resp.status_code, headers=out_headers)

    return endpoint
