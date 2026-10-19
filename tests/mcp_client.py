"""Talk to the app the way an MCP agent does (in-process, through Starlette's TestClient)."""
import json

from starlette.testclient import TestClient

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params=None, headers=None):
    r = client.post("/mcp", headers={**HEADERS, **(headers or {})},
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    if r.status_code != 200:
        return r
    if r.headers["content-type"].startswith("text/event-stream"):
        data = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
        return json.loads(data[-1])
    return r.json()


def tools(server):
    with TestClient(server.app) as c:
        return {t["name"]: t for t in rpc(c, "tools/list")["result"]["tools"]}


def call(server, name, **arguments):
    with TestClient(server.app) as c:
        res = rpc(c, "tools/call", {"name": name, "arguments": arguments})["result"]
    return res["content"][0]["text"]
