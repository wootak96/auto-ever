"""Persist a user's answer-style directive into their per-user chat_md doc.

Triggered only when query_analyze classifies intent as `instruction`. The
node:
  1. Loads the user's existing instruction markdown (empty when first time).
  2. Calls the judge LLM to merge the new directive into the markdown
     (add / update / remove / reset — all expressed by rewriting).
  3. Upserts the new markdown into chat_md (doc_id = user_id).
  4. Asks the generator LLM for a one-line Korean confirmation, which
     becomes the final answer surfaced to the user.

When user_id is empty the node still produces a friendly reply but skips
persistence — anonymous instructions cannot be remembered across turns.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app import prompts
from app.graph.nodes import PROGRESS_KEY
from app.graph.nodes._helpers import llm_text
from app.graph.state import RAGState
from app.services.instruction_store import get_user_md, update_user_md
from app.services.llm_factory import get_generator_llm, get_judge_llm


_NO_USER_REPLY = (
    "알겠습니다. 다만 로그인 정보가 없어 다음 대화에서는 기억하지 못해요."
)


async def instruction_save(state: RAGState) -> dict:
    utterance = state.get("current_query") or ""
    user_id = state.get("user_id") or ""

    if not utterance:
        return {
            "final_answer": "지침을 인식하지 못했어요. 다시 말씀해 주실 수 있을까요?",
            "sources": [],
            PROGRESS_KEY: "",
        }

    if not user_id:
        return {
            "final_answer": _NO_USER_REPLY,
            "sources": [],
            PROGRESS_KEY: "📝 지침 저장 — 로그인 정보 없음으로 메모리 저장 생략",
        }

    existing = await get_user_md(user_id)
    merge_prompt = prompts.INSTRUCTION_UPDATE.format(
        existing_md=existing or "(empty)",
        utterance=utterance,
    )
    updated_md = (await llm_text(get_judge_llm(), merge_prompt)).strip()

    # Defensive guard: the merge LLM occasionally returns nothing on
    # malformed input. Fall back to keeping the existing md.
    if not updated_md:
        updated_md = existing

    await update_user_md(user_id, updated_md)

    confirm_prompt = prompts.INSTRUCTION_CONFIRM.format(
        utterance=utterance,
        updated_md=updated_md,
    )
    response = await get_generator_llm().ainvoke(
        [HumanMessage(content=confirm_prompt)]
    )
    reply = (
        response.content if hasattr(response, "content") else str(response)
    ) or "알겠습니다."

    return {
        "final_answer": reply,
        "sources": [],
        PROGRESS_KEY: "📝 사용자 지침 저장 완료",
    }
