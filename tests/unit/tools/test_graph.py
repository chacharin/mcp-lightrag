"""Unit tests for tools/graph.py round 3A (read-only) tools."""

from __future__ import annotations

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.graph import (
    check_entity_exists,
    get_graph_labels,
    get_knowledge_graph,
    get_popular_labels,
    search_labels,
)
from tests.unit.conftest import make_ctx


async def test_get_graph_labels_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/label/list"
        return httpx.Response(200, json=["ศบท.", "DIME", "Tesla"])

    ctx, _client = make_ctx(handler)
    result = await get_graph_labels(ctx)

    assert result == ["ศบท.", "DIME", "Tesla"]


async def test_get_graph_labels_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await get_graph_labels(ctx)


async def test_get_popular_labels_sends_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json=["DIME", "Tesla"])

    ctx, _client = make_ctx(handler)
    result = await get_popular_labels(ctx, limit=5)

    assert result == ["DIME", "Tesla"]


async def test_get_popular_labels_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "bad key"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await get_popular_labels(ctx)

    assert exc_info.value.status_code == 403


async def test_search_labels_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "DIME"
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json=["DIME", "DIME Task Force"])

    ctx, _client = make_ctx(handler)
    result = await search_labels(ctx, q="DIME")

    assert "DIME" in result


async def test_search_labels_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await search_labels(ctx, q="DIME")


async def test_get_knowledge_graph_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["label"] == "DIME"
        assert request.url.params["max_depth"] == "3"
        assert request.url.params["max_nodes"] == "1000"
        return httpx.Response(200, json={"nodes": [{"id": "DIME"}], "edges": []})

    ctx, _client = make_ctx(handler)
    result = await get_knowledge_graph(ctx, label="DIME")

    assert result["nodes"][0]["id"] == "DIME"


async def test_get_knowledge_graph_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "label not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await get_knowledge_graph(ctx, label="bogus")

    assert exc_info.value.status_code == 404


async def test_check_entity_exists_true() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == "Tesla"
        return httpx.Response(200, json={"exists": True})

    ctx, _client = make_ctx(handler)
    result = await check_entity_exists(ctx, name="Tesla")

    assert result == {"exists": True}


async def test_check_entity_exists_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await check_entity_exists(ctx, name="Tesla")
