"""Query tools: `query` and `query_data` (plan.md section 4.1).

Both call LightRAG's current QueryRequest parameter set (the one that
replaced the deprecated `max_token_for_*` fields) and share every
parameter; `query_data` additionally skips LLM answer generation and
returns the raw retrieved entities/relations/chunks instead.

Every tool function here is a plain top-level async function so
tests/unit/tools/test_query.py can import and call it directly with a
fake ctx. `register()` is the only thing server.py calls.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field

from mcp_lightrag.tools._common import get_client

QueryMode = Literal["local", "global", "hybrid", "naive", "mix", "bypass"]


def _build_payload(
    *,
    query: str,
    mode: QueryMode,
    top_k: int | None,
    chunk_top_k: int | None,
    max_entity_tokens: int | None,
    max_relation_tokens: int | None,
    max_total_tokens: int | None,
    response_type: str | None,
    user_prompt: str | None,
    conversation_history: list[dict[str, Any]] | None,
    hl_keywords: list[str] | None,
    ll_keywords: list[str] | None,
    enable_rerank: bool | None,
    include_references: bool,
    include_chunk_content: bool,
    only_need_context: bool,
    only_need_prompt: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "include_references": include_references,
        "include_chunk_content": include_chunk_content,
    }
    if only_need_context:
        payload["only_need_context"] = True
    if only_need_prompt:
        payload["only_need_prompt"] = True
    optional = {
        "top_k": top_k,
        "chunk_top_k": chunk_top_k,
        "max_entity_tokens": max_entity_tokens,
        "max_relation_tokens": max_relation_tokens,
        "max_total_tokens": max_total_tokens,
        "response_type": response_type,
        "user_prompt": user_prompt,
        "conversation_history": conversation_history,
        "hl_keywords": hl_keywords,
        "ll_keywords": ll_keywords,
        "enable_rerank": enable_rerank,
    }
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    return payload


_QUERY_DESC = (
    "The question or instruction to answer using the knowledge base. Must not be empty."
)
_MODE_DESC = (
    "Retrieval mode. 'mix' (default) combines knowledge-graph and vector "
    "retrieval and is the best general-purpose choice. 'local' favors "
    "entities near the query, 'global' favors relationships, 'hybrid' "
    "combines local+global, 'naive' is plain vector search, and 'bypass' "
    "skips retrieval entirely and sends the query straight to the LLM."
)
_TOP_K_DESC = "Number of top items to retrieve: entities in 'local' mode, relationships in 'global' mode."
_CHUNK_TOP_K_DESC = "Number of text chunks to retrieve and keep after reranking."
_MAX_ENTITY_TOKENS_DESC = "Maximum tokens allocated to entity context."
_MAX_RELATION_TOKENS_DESC = "Maximum tokens allocated to relationship context."
_MAX_TOTAL_TOKENS_DESC = (
    "Maximum total token budget for the whole query context "
    "(entities + relations + chunks + system prompt)."
)
_RESPONSE_TYPE_DESC = "Desired response format, e.g. 'Multiple Paragraphs', 'Single Paragraph', 'Bullet Points'."
_USER_PROMPT_DESC = (
    "Extra instructions for the answering LLM. Does not affect retrieval."
)
_CONVERSATION_HISTORY_DESC = (
    "Prior turns for context only (not used for retrieval), as "
    "[{'role': 'user'|'assistant', 'content': '...'}, ...]."
)
_HL_KEYWORDS_DESC = "High-level keywords to prioritize in retrieval. Leave empty to let LightRAG derive them."
_LL_KEYWORDS_DESC = "Low-level keywords to refine retrieval focus. Leave empty to let LightRAG derive them."
_ENABLE_RERANK_DESC = (
    "Enable reranking of retrieved text chunks, if a rerank model is configured."
)
_INCLUDE_REFERENCES_DESC = (
    "Include the list of source documents the answer drew on. Keep this "
    "true (the default) so answers can cite which document they came from."
)
_INCLUDE_CHUNK_CONTENT_DESC = (
    "Include the actual chunk text in each reference (for debugging/evaluation); "
    "only applies when include_references is true."
)
_ONLY_NEED_CONTEXT_DESC = (
    "Return only the retrieved context, without generating an answer."
)
_ONLY_NEED_PROMPT_DESC = "Return only the assembled prompt, without calling the LLM."


async def query(
    ctx: Context[Any, Any],
    query: Annotated[str, Field(description=_QUERY_DESC)],
    mode: Annotated[QueryMode, Field(description=_MODE_DESC)] = "mix",
    top_k: Annotated[int | None, Field(description=_TOP_K_DESC, ge=1)] = None,
    chunk_top_k: Annotated[
        int | None, Field(description=_CHUNK_TOP_K_DESC, ge=1)
    ] = None,
    max_entity_tokens: Annotated[
        int | None, Field(description=_MAX_ENTITY_TOKENS_DESC, ge=1)
    ] = None,
    max_relation_tokens: Annotated[
        int | None, Field(description=_MAX_RELATION_TOKENS_DESC, ge=1)
    ] = None,
    max_total_tokens: Annotated[
        int | None, Field(description=_MAX_TOTAL_TOKENS_DESC, ge=1)
    ] = None,
    response_type: Annotated[str | None, Field(description=_RESPONSE_TYPE_DESC)] = None,
    user_prompt: Annotated[str | None, Field(description=_USER_PROMPT_DESC)] = None,
    conversation_history: Annotated[
        list[dict[str, Any]] | None, Field(description=_CONVERSATION_HISTORY_DESC)
    ] = None,
    hl_keywords: Annotated[
        list[str] | None, Field(description=_HL_KEYWORDS_DESC)
    ] = None,
    ll_keywords: Annotated[
        list[str] | None, Field(description=_LL_KEYWORDS_DESC)
    ] = None,
    enable_rerank: Annotated[
        bool | None, Field(description=_ENABLE_RERANK_DESC)
    ] = None,
    include_references: Annotated[
        bool, Field(description=_INCLUDE_REFERENCES_DESC)
    ] = True,
    include_chunk_content: Annotated[
        bool, Field(description=_INCLUDE_CHUNK_CONTENT_DESC)
    ] = False,
    only_need_context: Annotated[
        bool, Field(description=_ONLY_NEED_CONTEXT_DESC)
    ] = False,
    only_need_prompt: Annotated[
        bool, Field(description=_ONLY_NEED_PROMPT_DESC)
    ] = False,
) -> dict[str, Any]:
    """Answer a question using the knowledge base (RAG). Use this for any
    question about the content stored in LightRAG -- it retrieves relevant
    context and has an LLM compose the answer. Returns `response` (the
    answer text) and, by default, `references` (the source documents it
    drew on)."""
    client = get_client(ctx)
    payload = _build_payload(
        query=query,
        mode=mode,
        top_k=top_k,
        chunk_top_k=chunk_top_k,
        max_entity_tokens=max_entity_tokens,
        max_relation_tokens=max_relation_tokens,
        max_total_tokens=max_total_tokens,
        response_type=response_type,
        user_prompt=user_prompt,
        conversation_history=conversation_history,
        hl_keywords=hl_keywords,
        ll_keywords=ll_keywords,
        enable_rerank=enable_rerank,
        include_references=include_references,
        include_chunk_content=include_chunk_content,
        only_need_context=only_need_context,
        only_need_prompt=only_need_prompt,
    )
    return await client.request(
        "POST", "/query", json=payload, timeout=client.query_timeout
    )


async def query_data(
    ctx: Context[Any, Any],
    query: Annotated[str, Field(description=_QUERY_DESC)],
    mode: Annotated[QueryMode, Field(description=_MODE_DESC)] = "mix",
    top_k: Annotated[int | None, Field(description=_TOP_K_DESC, ge=1)] = None,
    chunk_top_k: Annotated[
        int | None, Field(description=_CHUNK_TOP_K_DESC, ge=1)
    ] = None,
    max_entity_tokens: Annotated[
        int | None, Field(description=_MAX_ENTITY_TOKENS_DESC, ge=1)
    ] = None,
    max_relation_tokens: Annotated[
        int | None, Field(description=_MAX_RELATION_TOKENS_DESC, ge=1)
    ] = None,
    max_total_tokens: Annotated[
        int | None, Field(description=_MAX_TOTAL_TOKENS_DESC, ge=1)
    ] = None,
    response_type: Annotated[str | None, Field(description=_RESPONSE_TYPE_DESC)] = None,
    user_prompt: Annotated[str | None, Field(description=_USER_PROMPT_DESC)] = None,
    conversation_history: Annotated[
        list[dict[str, Any]] | None, Field(description=_CONVERSATION_HISTORY_DESC)
    ] = None,
    hl_keywords: Annotated[
        list[str] | None, Field(description=_HL_KEYWORDS_DESC)
    ] = None,
    ll_keywords: Annotated[
        list[str] | None, Field(description=_LL_KEYWORDS_DESC)
    ] = None,
    enable_rerank: Annotated[
        bool | None, Field(description=_ENABLE_RERANK_DESC)
    ] = None,
) -> dict[str, Any]:
    """Retrieve the raw entities, relationships and text chunks relevant to
    a question, WITHOUT having LightRAG's LLM compose an answer. Use this
    instead of `query` when the caller (e.g. Hermes) wants to compose its
    own answer from the retrieved evidence. Always includes references."""
    client = get_client(ctx)
    payload = _build_payload(
        query=query,
        mode=mode,
        top_k=top_k,
        chunk_top_k=chunk_top_k,
        max_entity_tokens=max_entity_tokens,
        max_relation_tokens=max_relation_tokens,
        max_total_tokens=max_total_tokens,
        response_type=response_type,
        user_prompt=user_prompt,
        conversation_history=conversation_history,
        hl_keywords=hl_keywords,
        ll_keywords=ll_keywords,
        enable_rerank=enable_rerank,
        include_references=True,
        include_chunk_content=False,
        only_need_context=False,
        only_need_prompt=False,
    )
    return await client.request(
        "POST", "/query/data", json=payload, timeout=client.query_timeout
    )


def register(server: MCPServer[Any]) -> None:
    server.add_tool(query)
    server.add_tool(query_data)
