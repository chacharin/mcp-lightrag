"""The MCP endpoint as an agent sees it, the optional bearer token, and /health."""
import json

import httpx
import pytest
from starlette.testclient import TestClient

from tests.mcp_client import HEADERS, call, tools


def test_default_tools(load_server):
    t = tools(load_server())
    assert set(t) == {"lightrag_query", "lightrag_insert", "lightrag_list_documents"}
    mode = t["lightrag_query"]["inputSchema"]["properties"]["mode"]
    assert mode["enum"] == ["mix", "hybrid", "local", "global", "naive"] and mode["default"] == "hybrid"
    assert t["lightrag_query"]["inputSchema"]["required"] == ["query"]
    assert t["lightrag_insert"]["inputSchema"]["required"] == ["text"]


def test_read_only_server_has_no_insert(load_server):
    t = tools(load_server(ENABLE_INSERT="false"))
    assert "lightrag_insert" not in t and "lightrag_insert" not in t["lightrag_query"]["description"]


def test_kb_description_tells_the_agent_what_is_inside(load_server):
    t = tools(load_server(KB_DESCRIPTION="คู่มือการใช้งานผลิตภัณฑ์"))
    assert "คู่มือการใช้งานผลิตภัณฑ์" in t["lightrag_query"]["description"]


def test_mode_list_follows_settings(load_server):
    mode = tools(load_server(QUERY_MODES="naive,local", DEFAULT_MODE="local"))["lightrag_query"]["inputSchema"]["properties"]["mode"]
    assert mode["enum"] == ["naive", "local"] and mode["default"] == "local"
    assert "mix" not in mode["description"]


def test_an_invented_mode_falls_back_to_the_default(load_server, fake_lightrag):
    server = load_server()
    seen = fake_lightrag(lambda r: httpx.Response(200, json={"response": "ok", "references": []}))
    assert call(server, "lightrag_query", query="อะไร", mode="smart") == "ok"
    assert json.loads(seen[0].content)["mode"] == "hybrid"


def test_insert_through_mcp(load_server, fake_lightrag):
    server = load_server()
    seen = fake_lightrag(lambda r: httpx.Response(200, json={"status": "success"}))
    out = json.loads(call(server, "lightrag_insert", text="เนื้อหา", description="บันทึก 1"))
    assert out["file_source"] == "บันทึก-1" and seen[0].url.path == "/documents/text"


def test_empty_query_is_not_sent(load_server, fake_lightrag):
    server = load_server()
    seen = fake_lightrag(lambda r: httpx.Response(200, json={}))
    assert "empty" in call(server, "lightrag_query", query="   ")
    assert seen == []


@pytest.mark.parametrize("given,status", [(None, 401), ("Bearer wrong", 401), ("Bearer test-token-not-real", 200)])
def test_bearer_token(load_server, given, status):
    server = load_server(MCP_AUTH_TOKEN="test-token-not-real")
    with TestClient(server.app) as c:
        r = c.post("/mcp", headers={**HEADERS, **({"Authorization": given} if given else {})},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert r.status_code == status
        assert c.get("/health").status_code == 200          # /health never needs the token


def healthy(request):
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "healthy"})
    return httpx.Response(200, json={})


def health(server):
    with TestClient(server.app) as c:
        return c.get("/health").json()


def test_health_ok(load_server, fake_lightrag):
    server = load_server(LIGHTRAG_API_KEY="test-key-not-real-0123")
    fake_lightrag(healthy)
    h = health(server)
    assert h["ok"] is True and h["problems"] == [] and h["key_configured"] is True


def test_health_flags_the_example_key(load_server, fake_lightrag):
    server = load_server(LIGHTRAG_API_KEY="change-me")
    fake_lightrag(lambda r: httpx.Response(200 if r.url.path == "/health" else 401, json={}))
    h = health(server)
    assert h["ok"] is False and any(".env.example" in p for p in h["problems"])


def test_health_explains_an_unreachable_lightrag(load_server, fake_lightrag):
    server = load_server()

    def down(request):
        raise httpx.ConnectError("refused", request=request)

    fake_lightrag(down)
    h = health(server)
    assert h["ok"] is False and any("does not answer" in p for p in h["problems"])


def test_health_explains_an_empty_key_that_lightrag_needs(load_server, fake_lightrag):
    server = load_server()
    fake_lightrag(lambda r: httpx.Response(200 if r.url.path == "/health" else 401, json={}))
    h = health(server)
    assert h["ok"] is False and any("it is empty" in p for p in h["problems"])
