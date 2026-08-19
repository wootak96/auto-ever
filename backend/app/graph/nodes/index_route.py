"""Per-sub-query index routing.

Runs BEFORE query_rewrite so rewrites can be index-aware: each sub-query is
routed to one or more indices, and a single sub-query routed to multiple
indices will produce multiple per-index search plans downstream (the
confluence_docs corpus is Korean, ES/Kafka docs are English, so BM25 strings
differ per index).

For a decomposed query like "ES와 Kafka의 차이"  →  ["ES throughput",
"Kafka throughput"] each sub-query routes to its own index rather than
searching both indices for both sub-queries.
"""

from __future__ import annotations

import asyncio

from app import prompts
from app.config import get_settings
from app.graph.nodes import PROGRESS_KEY
from app.graph.nodes._helpers import llm_json
from app.graph.nodes.query_analyze import _has_domain_term, _has_internal_term
from app.graph.state import RAGState
from app.services.llm_factory import get_judge_llm


# Confluence alias key in `index_alias_map`. The router output is the resolved
# index name (`confluence_docs`); this constant names the alias used in the
# LLM prompt and the JSON schema (`{"indices": [...]}`).
_CONFLUENCE_ALIAS = "confluence"


async def _route_one(query: str, alias_map: dict[str, str]) -> list[str]:
    data = await llm_json(get_judge_llm(), prompts.INDEX_ROUTE.format(query=query))
    aliases = data.get("indices") or []
    if not isinstance(aliases, list):
        aliases = []
    valid = [a for a in aliases if a in alias_map]
    if not valid:
        valid = list(alias_map.keys())  # fallback: search all for recall
    # Force-include confluence whenever an organisation-internal term
    # appears — a product name, an internal acronym, an office, a namespace
    # prefix (see `app.internal_terms`). The LLM may not recognize terms
    # that exist only inside one company, but the user's intent is
    # unambiguous: those docs live only in the internal wiki. Belt-and-
    # braces over the LLM.
    if (
        _CONFLUENCE_ALIAS in alias_map
        and _has_internal_term(query)
        and _CONFLUENCE_ALIAS not in valid
    ):
        valid.append(_CONFLUENCE_ALIAS)
    return [alias_map[a] for a in valid]


async def route_query(query: str) -> list[str]:
    """Single-query index routing, reused by es_count / es_list paths.

    Short-circuits to all indices when the query contains no domain keyword
    at all (meta-collection questions like "전체 문서 몇 개?", "사내 자료
    얼마나?"), avoiding an unnecessary LLM call and a known LLM bias toward
    picking the first listed index. Otherwise delegates to the same
    INDEX_ROUTE prompt as the multi-sub-query routing.
    """
    settings = get_settings()
    if not _has_domain_term(query):
        return list(settings.index_alias_map.values())
    return await _route_one(query, settings.index_alias_map)


async def index_route(state: RAGState) -> dict:
    settings = get_settings()
    alias_map = settings.index_alias_map

    if state.get("intent") == "chitchat":
        return {"target_indices_per_query": [], PROGRESS_KEY: ""}

    queries = state.get("sub_queries") or []
    if not queries:
        return {
            "target_indices_per_query": [],
            PROGRESS_KEY: "🧭 인덱스 라우팅: (서브쿼리 없음)",
        }

    routed = await asyncio.gather(*[_route_one(q, alias_map) for q in queries])
    target_indices_per_query = [list(r) for r in routed]

    # Brief summary for UI: aliases chosen for each sub-query.
    reverse = {v: k for k, v in alias_map.items()}
    summary = " | ".join(
        ",".join(reverse.get(i, i) for i in indices) for indices in target_indices_per_query
    )
    return {
        "target_indices_per_query": target_indices_per_query,
        PROGRESS_KEY: f"🧭 인덱스 라우팅: {summary}",
    }
