"""Unit tests for tools/graph.py round 3B (add/edit) tools."""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest

from mcp_lightrag.errors import LightRAGError
from mcp_lightrag.tools.graph import (
    create_entity,
    create_relation,
    edit_entity,
    edit_relation,
    merge_entities,
)
from tests.unit.conftest import make_ctx


async def test_create_entity_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/entity/create"
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": "ok",
                "data": {"entity_name": "Tesla"},
            },
        )

    ctx, _client = make_ctx(handler)
    result = await create_entity(
        ctx, entity_name="Tesla", entity_data={"description": "EV maker"}
    )

    assert result["status"] == "success"
    assert seen_body == {
        "entity_name": "Tesla",
        "entity_data": {"description": "EV maker"},
    }


async def test_create_entity_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Entity name cannot be empty"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await create_entity(ctx, entity_name="", entity_data={})

    assert exc_info.value.status_code == 400


async def test_edit_entity_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(
            200, json={"status": "success", "message": "updated", "data": {}}
        )

    ctx, _client = make_ctx(handler)
    result = await edit_entity(
        ctx, entity_name="Tesla", updated_data={"description": "new"}, allow_rename=True
    )

    assert result["status"] == "success"
    assert seen_body == {
        "entity_name": "Tesla",
        "updated_data": {"description": "new"},
        "allow_rename": True,
        "allow_merge": False,
    }


async def test_edit_entity_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Entity not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError) as exc_info:
        await edit_entity(ctx, entity_name="Bogus", updated_data={})

    assert exc_info.value.status_code == 404


async def test_create_relation_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "success", "message": "ok"})

    ctx, _client = make_ctx(handler)
    await create_relation(
        ctx,
        source_entity="Elon Musk",
        target_entity="Tesla",
        relation_data={"description": "CEO of"},
    )

    assert seen_body == {
        "source_entity": "Elon Musk",
        "target_entity": "Tesla",
        "relation_data": {"description": "CEO of"},
    }


async def test_create_relation_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "source entity not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await create_relation(
            ctx, source_entity="Bogus", target_entity="Tesla", relation_data={}
        )


async def test_edit_relation_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "success"})

    ctx, _client = make_ctx(handler)
    await edit_relation(
        ctx, source_id="Elon Musk", target_id="Tesla", updated_data={"weight": 2.0}
    )

    assert seen_body == {
        "source_id": "Elon Musk",
        "target_id": "Tesla",
        "updated_data": {"weight": 2.0},
    }


async def test_edit_relation_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "relation not found"})

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await edit_relation(ctx, source_id="a", target_id="b", updated_data={})


async def test_merge_entities_success() -> None:
    seen_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/entities/merge"
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json={"status": "success"})

    ctx, _client = make_ctx(handler)
    await merge_entities(
        ctx,
        entities_to_change=["Elon Msk", "Ellon Musk"],
        entity_to_change_into="Elon Musk",
    )

    assert seen_body == {
        "entities_to_change": ["Elon Msk", "Ellon Musk"],
        "entity_to_change_into": "Elon Musk",
    }


async def test_merge_entities_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    ctx, _client = make_ctx(handler)

    with pytest.raises(LightRAGError):
        await merge_entities(ctx, entities_to_change=["a"], entity_to_change_into="b")
