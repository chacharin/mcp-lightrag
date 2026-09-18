"""Unit tests for tools/graph.py round 3C (delete) tools."""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.graph import delete_entity, delete_relation
from tests.unit.conftest import make_ctx


async def test_delete_entity_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/graph/entity/delete"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "success", "doc_id": "", "message": "deleted"}
        )

    ctx, _client = make_ctx(handler)
    result = await delete_entity(ctx, entity_name="Tesla")

    assert result["status"] == "success"
    assert seen_body == {"entity_name": "Tesla"}


async def test_delete_entity_not_found_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Entity not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await delete_entity(ctx, entity_name="Bogus")

    assert exc_info.value.status_code == 404


async def test_delete_relation_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/graph/relation/delete"
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "success", "message": "deleted"})

    ctx, _client = make_ctx(handler)
    result = await delete_relation(
        ctx, source_entity="Elon Musk", target_entity="Tesla"
    )

    assert result["status"] == "success"
    assert seen_body == {"source_entity": "Elon Musk", "target_entity": "Tesla"}


async def test_delete_relation_not_found_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Relation not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await delete_relation(ctx, source_entity="a", target_entity="b")

    assert exc_info.value.status_code == 404
