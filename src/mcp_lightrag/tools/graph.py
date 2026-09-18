"""Knowledge-graph tools (plan.md section 4.3).

Round 3A (read-only): get_graph_labels, get_popular_labels, search_labels,
get_knowledge_graph, check_entity_exists.

Round 3B (add/edit): create_entity, edit_entity, create_relation,
edit_relation, merge_entities.

Round 3C (delete): delete_entity, delete_relation.

Every tool function here is a plain top-level async function so
tests/unit/tools/test_graph.py can import and call it directly with a
fake ctx. `register()` is the only thing server.py calls.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from mcp_lightrag.tools._common import get_client


async def get_graph_labels(ctx: Context[Any, Any]) -> list[str]:
    """List every entity label (name) currently in the knowledge graph.
    Can be long on a large knowledge base -- prefer `get_popular_labels`
    or `search_labels` when looking for something specific."""
    client = get_client(ctx)
    return await client.request("GET", "/graph/label/list")


async def get_popular_labels(
    ctx: Context[Any, Any],
    limit: Annotated[
        int,
        Field(description="Maximum number of labels to return.", ge=1, le=1000),
    ] = 300,
) -> list[str]:
    """List entity labels sorted by how connected they are (node degree),
    most-connected first -- a quick way to see what the knowledge graph is
    mostly about."""
    client = get_client(ctx)
    return await client.request("GET", "/graph/label/popular", params={"limit": limit})


async def search_labels(
    ctx: Context[Any, Any],
    q: Annotated[
        str,
        Field(
            description="Search text to fuzzy-match against entity labels, e.g. 'DIME'."
        ),
    ],
    limit: Annotated[
        int,
        Field(description="Maximum number of matching labels to return.", ge=1, le=100),
    ] = 50,
) -> list[str]:
    """Find entity labels whose name fuzzy-matches a search string. Use
    this to locate entities related to a topic before asking about them
    with `query`, or before `get_knowledge_graph`."""
    client = get_client(ctx)
    return await client.request(
        "GET", "/graph/label/search", params={"q": q, "limit": limit}
    )


async def get_knowledge_graph(
    ctx: Context[Any, Any],
    label: Annotated[str, Field(description="Entity label to center the subgraph on.")],
    max_depth: Annotated[
        int, Field(description="Maximum number of hops from the starting label.", ge=1)
    ] = 3,
    max_nodes: Annotated[
        int, Field(description="Maximum number of nodes to return.", ge=1)
    ] = 1000,
) -> dict[str, Any]:
    """Retrieve a connected subgraph (nodes and edges) around one entity
    label. Nodes closer to the label, and more connected nodes, are kept
    first when the graph is larger than `max_nodes`."""
    client = get_client(ctx)
    return await client.request(
        "GET",
        "/graphs",
        params={"label": label, "max_depth": max_depth, "max_nodes": max_nodes},
    )


async def check_entity_exists(
    ctx: Context[Any, Any],
    name: Annotated[str, Field(description="Exact entity name to check.")],
) -> dict[str, bool]:
    """Check whether an entity with an exact name already exists in the
    knowledge graph. Call this before `create_entity` or `edit_entity`
    (rename) to avoid an unintended collision."""
    client = get_client(ctx)
    return await client.request("GET", "/graph/entity/exists", params={"name": name})


async def create_entity(
    ctx: Context[Any, Any],
    entity_name: Annotated[str, Field(description="Unique name for the new entity.")],
    entity_data: Annotated[
        dict[str, Any],
        Field(
            description="Entity properties, e.g. {'description': '...', 'entity_type': 'ORGANIZATION'}."
        ),
    ],
) -> dict[str, Any]:
    """Create a new entity in the knowledge graph. Call
    `check_entity_exists` first to avoid an unintended duplicate."""
    client = get_client(ctx)
    return await client.request(
        "POST",
        "/graph/entity/create",
        json={"entity_name": entity_name, "entity_data": entity_data},
    )


async def edit_entity(
    ctx: Context[Any, Any],
    entity_name: Annotated[str, Field(description="Name of the entity to update.")],
    updated_data: Annotated[
        dict[str, Any],
        Field(
            description="Properties to update. Only entity_name (rename target), entity_type, description, source_id and file_path are accepted."
        ),
    ],
    allow_rename: Annotated[
        bool,
        Field(
            description="Allow renaming the entity (when updated_data includes a new entity_name)."
        ),
    ] = False,
    allow_merge: Annotated[
        bool,
        Field(
            description="When a rename collides with an existing entity, merge into it instead of failing."
        ),
    ] = False,
) -> dict[str, Any]:
    """Update an entity's properties, optionally renaming it (and merging
    it into an existing entity of the same new name, if allowed)."""
    client = get_client(ctx)
    return await client.request(
        "POST",
        "/graph/entity/edit",
        json={
            "entity_name": entity_name,
            "updated_data": updated_data,
            "allow_rename": allow_rename,
            "allow_merge": allow_merge,
        },
    )


async def create_relation(
    ctx: Context[Any, Any],
    source_entity: Annotated[
        str, Field(description="Name of the source entity. Must already exist.")
    ],
    target_entity: Annotated[
        str, Field(description="Name of the target entity. Must already exist.")
    ],
    relation_data: Annotated[
        dict[str, Any],
        Field(
            description="Relationship properties, e.g. {'description': '...', 'keywords': '...', 'weight': 1.0}."
        ),
    ],
) -> dict[str, Any]:
    """Create a relationship between two entities that both already exist
    in the knowledge graph."""
    client = get_client(ctx)
    return await client.request(
        "POST",
        "/graph/relation/create",
        json={
            "source_entity": source_entity,
            "target_entity": target_entity,
            "relation_data": relation_data,
        },
    )


async def edit_relation(
    ctx: Context[Any, Any],
    source_id: Annotated[
        str, Field(description="Source entity name of the relationship to update.")
    ],
    target_id: Annotated[
        str, Field(description="Target entity name of the relationship to update.")
    ],
    updated_data: Annotated[
        dict[str, Any], Field(description="Relationship properties to update.")
    ],
) -> dict[str, Any]:
    """Update the properties of an existing relationship between two
    entities."""
    client = get_client(ctx)
    return await client.request(
        "POST",
        "/graph/relation/edit",
        json={
            "source_id": source_id,
            "target_id": target_id,
            "updated_data": updated_data,
        },
    )


async def merge_entities(
    ctx: Context[Any, Any],
    entities_to_change: Annotated[
        list[str],
        Field(
            description="Entity names to merge and remove -- typically duplicates or misspellings, e.g. ['Elon Msk', 'Ellon Musk']."
        ),
    ],
    entity_to_change_into: Annotated[
        str,
        Field(
            description="Target entity name that receives all relationships from the source entities. Created if it doesn't already exist."
        ),
    ],
) -> dict[str, Any]:
    """Merge one or more duplicate or misspelled entities into a single
    target entity. The merged-from entities are removed once this
    succeeds and this cannot be undone -- double check the names first."""
    client = get_client(ctx)
    return await client.request(
        "POST",
        "/graph/entities/merge",
        json={
            "entities_to_change": entities_to_change,
            "entity_to_change_into": entity_to_change_into,
        },
    )


async def delete_entity(
    ctx: Context[Any, Any],
    entity_name: Annotated[str, Field(description="Name of the entity to delete.")],
) -> dict[str, Any]:
    """DESTRUCTIVE: permanently deletes an entity and all its
    relationships from the knowledge graph. This cannot be undone."""
    client = get_client(ctx)
    return await client.request(
        "DELETE", "/graph/entity/delete", json={"entity_name": entity_name}
    )


async def delete_relation(
    ctx: Context[Any, Any],
    source_entity: Annotated[str, Field(description="Name of the source entity.")],
    target_entity: Annotated[str, Field(description="Name of the target entity.")],
) -> dict[str, Any]:
    """DESTRUCTIVE: permanently deletes the relationship between two
    entities from the knowledge graph. This cannot be undone. The
    entities themselves are not deleted."""
    client = get_client(ctx)
    return await client.request(
        "DELETE",
        "/graph/relation/delete",
        json={"source_entity": source_entity, "target_entity": target_entity},
    )


def register(server: MCPServer[Any]) -> None:
    server.add_tool(get_graph_labels)
    server.add_tool(get_popular_labels)
    server.add_tool(search_labels)
    server.add_tool(get_knowledge_graph)
    server.add_tool(check_entity_exists)
    server.add_tool(create_entity)
    server.add_tool(edit_entity)
    server.add_tool(create_relation)
    server.add_tool(edit_relation)
    server.add_tool(merge_entities)
    server.add_tool(delete_entity)
    server.add_tool(delete_relation)
