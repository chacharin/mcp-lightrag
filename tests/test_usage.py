"""The usage log (one record per tool call, read back through GET /usage) and the LLM meter."""
import json

import httpx
import pytest
from starlette.testclient import TestClient

from tests.mcp_client import call

USAGE = {"prompt_tokens": 900, "completion_tokens": 60, "total_tokens": 960, "cost": 0.0012,
         "prompt_tokens_details": {"cached_tokens": 100}, "completion_tokens_details": {"reasoning_tokens": 12}}


def records(client, **params):
    return client.get("/usage", params=params).json()["records"]


@pytest.fixture
def upstream(monkeypatch):
    """upstream(handler): the provider behind the meter; returns the requests it received."""
    from app import meter

    def install(handler):
        seen = []

        def record(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(meter, "transport", httpx.MockTransport(record))
        return seen

    return install


def test_tool_calls_are_logged_without_text(load_server, fake_lightrag):
    server = load_server()
    fake_lightrag(lambda r: httpx.Response(200, json={"response": "คำตอบลับ", "references": []}))
    call(server, "lightrag_query", query="คำถามลับ", mode="mix")
    (rec,) = records(TestClient(server.app))      # no lifespan: the MCP session manager runs once per app
    assert rec["kind"] == "mcp_tool" and rec["tool"] == "lightrag_query" and rec["status"] == "ok"
    assert rec["detail"]["mode"] == "mix" and rec["detail"]["query_chars"] == len("คำถามลับ")
    assert "ลับ" not in json.dumps(rec, ensure_ascii=False)


def test_failed_tool_call_is_logged_as_error(load_server, fake_lightrag):
    server = load_server()
    fake_lightrag(lambda r: httpx.Response(401, text="no"))
    call(server, "lightrag_query", query="q")
    (rec,) = records(TestClient(server.app))      # no lifespan: the MCP session manager runs once per app
    assert rec["status"] == "error" and rec["error"].startswith("LightRAG error HTTP 401")


def test_usage_needs_the_token_when_set(load_server):
    with TestClient(load_server(MCP_AUTH_TOKEN="t0ken").app) as c:
        assert c.get("/usage").status_code == 401
        assert c.get("/usage", headers={"Authorization": "Bearer t0ken"}).json()["environment"]["component"] \
            == "mcp-lightrag"


def test_meter_is_off_by_default(load_server):
    with TestClient(load_server().app) as c:
        assert c.post("/meter/v1/chat/completions", json={}).status_code == 404


def test_meter_passes_chat_through_and_logs_tokens(load_server, upstream):
    seen = upstream(lambda r: httpx.Response(200, json={
        "model": "google/gemma-4-31b-it", "provider": "Google",
        "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}], "usage": USAGE}))
    with TestClient(load_server(METER_UPSTREAM="https://provider.test/api/v1").app) as c:
        r = c.post("/meter/v1/chat/completions", json={"model": "m", "messages": []},
                   headers={"Authorization": "Bearer sk-lightrag-own-key"})
        (rec,) = records(c)
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "answer"
    assert str(seen[0].url) == "https://provider.test/api/v1/v1/chat/completions" or \
        str(seen[0].url).endswith("/chat/completions")
    assert seen[0].headers["authorization"] == "Bearer sk-lightrag-own-key"      # LightRAG's own key, untouched
    assert rec["component"] == "lightrag" and rec["kind"] == "llm_call"
    assert (rec["input_tokens"], rec["cache_read_tokens"], rec["output_tokens"], rec["reasoning_tokens"]) \
        == (800, 100, 60, 12)
    assert rec["cost_usd"] == 0.0012 and "sk-lightrag" not in json.dumps(rec)


def test_meter_logs_embeddings(load_server, upstream):
    upstream(lambda r: httpx.Response(200, json={"model": "qwen/qwen3-embedding-8b", "data": [],
                                                 "usage": {"prompt_tokens": 300, "total_tokens": 300}}))
    with TestClient(load_server(METER_UPSTREAM="https://provider.test/api").app) as c:
        c.post("/meter/embeddings", json={"model": "e", "input": ["a", "b"]})
        (rec,) = records(c)
    assert rec["kind"] == "embedding_call" and rec["input_tokens"] == 300 and rec["output_tokens"] == 0
    assert rec["detail"]["inputs"] == 2


def test_meter_streams_and_reads_usage_from_the_last_chunk(load_server, upstream):
    sse = ('data: {"model":"m","choices":[{"delta":{"content":"he"}}]}\n\n'
           'data: {"model":"m","choices":[{"delta":{"content":"llo"},"finish_reason":"stop"}]}\n\n'
           'data: {"model":"m","choices":[],"usage":{"prompt_tokens":50,"completion_tokens":2,"total_tokens":52}}\n\n'
           'data: [DONE]\n\n')
    upstream(lambda r: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"}))
    with TestClient(load_server(METER_UPSTREAM="https://provider.test/api").app) as c:
        r = c.post("/meter/chat/completions", json={"model": "m", "stream": True, "messages": []})
        assert r.text == sse
        (rec,) = records(c)
    assert (rec["input_tokens"], rec["output_tokens"], rec["finish_reason"]) == (50, 2, "stop")
    assert rec["detail"]["stream"] is True and rec["ttfb_s"] is not None


def test_meter_reports_an_unreachable_upstream(load_server, upstream):
    def fail(r):
        raise httpx.ConnectError("down")
    upstream(fail)
    with TestClient(load_server(METER_UPSTREAM="https://provider.test/api").app) as c:
        assert c.post("/meter/chat/completions", json={}).status_code == 502
        (rec,) = records(c)
    assert rec["status"] == "error" and rec["error"] == "ConnectError"
