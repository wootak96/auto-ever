"""Debug-mode answer node — explains why a prior bot answer came out the way
it did, by replaying the stored RAG trace.

Reads up to 3 most recent turns from the user's `{user_id}_logs` index, hands
them to the generator LLM, and lets it pick the relevant turn (the user might
be asking about the most recent one, or about an earlier one referenced by
topic or position). The output is streamed via on_chat_model_stream just like
the regular generate node — chat.py adds 'debug_explain' to its
node-name allowlist so tokens reach the SSE client.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app import prompts
from app.graph.nodes import PROGRESS_KEY
from app.graph.nodes.generate import _format_user_md_block
from app.graph.state import RAGState
from app.services.instruction_store import get_user_md
from app.services.llm_factory import get_generator_llm
from app.services.log_store import fetch_recent_turns


_RECENT_N = 3


def _render_turns(turns: list[dict]) -> str:
    """Render recent turns into a numbered text block for the LLM prompt.

    Turn 1 is the most recent. Each block contains question / final answer
    plus the structured trace fields most useful for explaining outcomes
    (intent, search_intent, sub_queries, search_plans, sufficiency, sources)
    and the raw progress_log so the LLM can quote specific lines.
    """
    if not turns:
        return "(저장된 최근 턴이 없습니다.)"

    blocks: list[str] = []
    for i, t in enumerate(turns, 1):
        question = (t.get("question") or "").strip()
        final = (t.get("final_answer") or "").strip()
        progress = (t.get("progress_log") or "").strip()
        intent = t.get("intent") or ""
        search_intent = t.get("search_intent") or ""
        sub_queries = t.get("sub_queries") or []
        target_indices = t.get("target_indices") or []
        index_routing = t.get("index_routing") or []
        metadata_filters = t.get("metadata_filters") or {}
        forced_indices = t.get("forced_indices") or []
        plans = t.get("search_plans") or []
        candidates = t.get("candidates") or []
        sufficient = t.get("sufficient")
        reason = t.get("sufficiency_reason") or ""
        sources = t.get("sources") or []
        retry_count = t.get("retry_count")

        lines = [
            f"━━━ Turn {i} ━━━",
            f"질문: {question}",
            f"intent: {intent} | search_intent: {search_intent}"
            + (f" | retry_count: {retry_count}" if retry_count else ""),
        ]
        if forced_indices:
            lines.append(
                f"forced_indices (re_search 사용자 지정): {forced_indices}"
            )
        if sub_queries:
            lines.append(f"sub_queries: {sub_queries}")
        if index_routing:
            lines.append("index_routing (sub_query별 라우팅):")
            for r in index_routing:
                lines.append(
                    f"  - sub_query={r.get('sub_query', '')!r} → {r.get('indices', [])}"
                )
        elif target_indices:
            lines.append(f"target_indices: {target_indices}")
        if metadata_filters:
            lines.append(f"metadata_filters (키워드 추출): {metadata_filters}")
        if plans:
            lines.append("search_plans:")
            for p in plans:
                lines.append(
                    f"  - [{p.get('index', '')}] sub_query={p.get('sub_query', '')!r} "
                    f"bm25={p.get('bm25', '')!r} semantic={p.get('semantic', '')!r}"
                )
        if candidates:
            used_count = sum(1 for c in candidates if c.get("used"))
            lines.append(
                f"candidates ({used_count}/{len(candidates)} 답변 인용):"
            )
            for j, c in enumerate(candidates, 1):
                mark = "✓" if c.get("used") else "·"
                title = c.get("title", "") or "(제목 없음)"
                score = c.get("score", 0.0)
                lines.append(f"  {mark} [{j}] {title} (score={score:.3f})")
        if sufficient is not None:
            lines.append(f"sufficient: {sufficient} | reason: {reason}")
        groundedness = t.get("groundedness") or {}
        if groundedness:
            g_total = groundedness.get("total_claims", 0)
            g_supp = groundedness.get("supported_count", 0)
            g_score = float(groundedness.get("score") or 0.0)
            lines.append(
                f"groundedness: grounded={groundedness.get('grounded')} "
                f"({g_supp}/{g_total} 주장 근거 있음, score={g_score:.2f})"
            )
            for c in (groundedness.get("claims") or [])[:5]:
                mark = "✓" if c.get("supported") else "✗"
                lines.append(
                    f"  {mark} {c.get('claim', '')[:80]} "
                    f"cites={c.get('citations', [])} — {c.get('reason', '')[:80]}"
                )
        token_usage = t.get("token_usage") or {}
        if token_usage:
            lines.append(
                f"token_usage: in={token_usage.get('total_input', 0)} "
                f"out={token_usage.get('total_output', 0)} "
                f"total={token_usage.get('total_tokens', 0)} "
                f"({token_usage.get('llm_calls', 0)} LLM 호출)"
            )
            for n in token_usage.get("by_node") or []:
                lines.append(
                    f"  - {n.get('node', '')}: "
                    f"in={n.get('input', 0)} out={n.get('output', 0)} "
                    f"total={n.get('total', 0)} (calls={n.get('calls', 0)})"
                )
        if sources:
            lines.append("sources:")
            for s in sources:
                title = s.get("title", "")
                url = s.get("url", "")
                lines.append(f"  - {title} ({url})")
        if progress:
            lines.append("--- 진행 trace (UI에 표시됐던 내용) ---")
            lines.append(progress)
        lines.append("--- 최종 답변 ---")
        lines.append(final or "(빈 답변)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def debug_explain(state: RAGState) -> dict:
    user_id = state.get("user_id") or ""
    session_id = state.get("session_id") or ""
    query = state.get("resolved_query") or state.get("current_query") or ""

    if not user_id:
        return {
            "final_answer": (
                "디버깅 모드는 로그인된 사용자에 한해 동작합니다 "
                "(현재 요청에 user_id가 포함되지 않아 로그를 조회할 수 없습니다)."
            ),
            "sources": [],
            PROGRESS_KEY: "🐛 디버깅 모드: user_id 미전송 — 로그 조회 불가",
        }
    if not session_id:
        return {
            "final_answer": (
                "디버깅 모드는 세션 단위로 동작합니다 "
                "(현재 요청에 session_id가 포함되지 않아 동일 세션의 이전 턴을 조회할 수 없습니다)."
            ),
            "sources": [],
            PROGRESS_KEY: "🐛 디버깅 모드: session_id 미전송 — 로그 조회 불가",
        }

    turns = await fetch_recent_turns(user_id, session_id=session_id, n=_RECENT_N)

    if not turns:
        return {
            "final_answer": "현재 세션에 최근 대화 기록이 없어 디버깅할 수 없습니다.",
            "sources": [],
            PROGRESS_KEY: "🐛 디버깅 모드: 현재 세션의 최근 로그 없음",
        }

    context = _render_turns(turns)
    user_md_block = _format_user_md_block(await get_user_md(user_id))
    prompt = prompts.DEBUG_EXPLAIN.format(
        query=query, turns=context, user_md_block=user_md_block
    )

    response = await get_generator_llm().ainvoke([HumanMessage(content=prompt)])
    content = response.content if hasattr(response, "content") else str(response)

    # Match generate / general_chat: no separate progress line — the answer
    # streams directly after the separator. The "최근 N턴 분석 완료" message
    # was redundant once the actual explanation arrives.
    return {
        "final_answer": content,
        "sources": [],
        PROGRESS_KEY: "",
    }
