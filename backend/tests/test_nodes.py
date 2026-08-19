"""Per-node tests with mocked LLM."""

import pytest

from app import internal_terms
from app.graph.nodes import PROGRESS_KEY
from app.graph.nodes.generate import generate
from app.graph.nodes.hybrid_retrieve import hybrid_retrieve
from app.graph.nodes.index_route import index_route
from app.graph.nodes.metadata_extract import metadata_extract
from app.graph.nodes.query_analyze import query_analyze
from app.graph.nodes.query_decompose import query_decompose
from app.graph.nodes.query_reform import query_reform
from app.graph.nodes.query_rewrite import query_rewrite
from app.graph.nodes.self_check import self_check, should_retry


# Taken from whichever terms file is active rather than written literally, so
# these tests exercise the real routing path on a deployment that supplies its
# own vocabulary and still pass on a clean checkout that only has the example.
INTERNAL_TERM = internal_terms.example_term()


@pytest.mark.asyncio
async def test_query_analyze_question(stub_judge):
    stub_judge(['{"intent": "question"}'])
    state = {"current_query": "RRF가 뭐야?", "messages": []}
    out = await query_analyze(state)
    assert out["intent"] == "question"
    assert "resolved_query" not in out  # reform is now a separate node
    assert PROGRESS_KEY in out


@pytest.mark.asyncio
async def test_query_analyze_chitchat(stub_judge):
    stub_judge(['{"intent": "chitchat"}'])
    state = {"current_query": "안녕", "messages": []}
    out = await query_analyze(state)
    assert out["intent"] == "chitchat"


@pytest.mark.asyncio
async def test_query_analyze_invalid_intent_falls_back(stub_judge):
    stub_judge(['{"intent": "garbage"}'])
    out = await query_analyze({"current_query": "x", "messages": []})
    assert out["intent"] == "question"


@pytest.mark.asyncio
async def test_query_analyze_domain_words_override_general(stub_judge):
    """If LLM misclassifies a domain question as general, the regex safety net
    kicks in and routes it to the search path."""
    stub_judge(['{"intent": "general"}'])
    out = await query_analyze(
        {"current_query": "Elasticsearch랑 Kafka 비교해줘", "messages": []}
    )
    assert out["intent"] == "question"  # overridden from general


@pytest.mark.asyncio
async def test_query_analyze_confluence_keywords_override_general(stub_judge):
    """Internal-wiki vocabulary triggers the safety net even with no ES/Kafka
    keywords — confluence-only questions must reach the search pipeline."""
    stub_judge(['{"intent": "general"}'])
    out = await query_analyze(
        {"current_query": "운영 가이드 어디 있어?", "messages": []}
    )
    assert out["intent"] == "question"


# ---- es_list size extraction ----


@pytest.mark.parametrize(
    "query,expected",
    [
        # Default when no size hint
        ("어떤 문서들이 있어?", 30),
        ("문서 목록 보여줘", 30),
        ("", 30),
        # Numeric with 개/건 suffix
        ("10개 보여줘", 10),
        ("5 건만", 5),
        ("100개씩 알려줘", 100),
        # "All" markers bump to max
        ("전체 문서 다 보여줘", 1000),
        ("모든 문서 목록", 1000),
        ("모두 보여줘", 1000),
        # False-positive guards: bare number must NOT match (no 개/건 suffix)
        ("최근 30일 자료", 30),  # default — '30일' has no 개/건, falls through
        ("2024년 문서", 30),
        # Clamp to MAX
        ("99999개 보여줘", 1000),
        # Floor at 1
        ("0개", 1),
    ],
)
def test_es_list_extract_size(query, expected):
    from app.graph.nodes.es_list import _extract_size

    assert _extract_size(query) == expected


@pytest.mark.asyncio
async def test_query_analyze_meeting_notes_override_general(stub_judge):
    stub_judge(['{"intent": "general"}'])
    out = await query_analyze(
        {"current_query": "어제 회의록 좀 보여줘", "messages": []}
    )
    assert out["intent"] == "question"


@pytest.mark.asyncio
async def test_query_analyze_debug_pattern_override_question(stub_judge):
    """Debug pattern overrides even a `question` LLM verdict — meta-questions
    about prior answers must reach debug_explain, not the search path."""
    stub_judge(['{"intent": "question"}'])
    out = await query_analyze(
        {"current_query": "왜 답변이 이렇게 나왔어?", "messages": []}
    )
    assert out["intent"] == "debugging"


@pytest.mark.asyncio
async def test_query_analyze_debug_pattern_overrides_domain_words(stub_judge):
    """Even when the query contains domain words like 'Kafka', if it's
    questioning a prior answer it must go to debug, not retrieval."""
    stub_judge(['{"intent": "question"}'])
    out = await query_analyze(
        {"current_query": "왜 Kafka 답변이 이렇게 나왔어?", "messages": []}
    )
    assert out["intent"] == "debugging"


@pytest.mark.asyncio
async def test_query_analyze_debug_intent_from_llm_passes_through(stub_judge):
    """LLM-emitted `debugging` is whitelisted (no longer demoted to question)."""
    stub_judge(['{"intent": "debugging"}'])
    out = await query_analyze(
        {"current_query": "방금 답변 어디서 가져온거야?", "messages": []}
    )
    assert out["intent"] == "debugging"


@pytest.mark.asyncio
async def test_query_analyze_no_domain_words_keeps_general(stub_judge):
    """No domain keywords -> the safety net does not interfere with general."""
    stub_judge(['{"intent": "general"}'])
    out = await query_analyze({"current_query": "오늘 날씨 어때?", "messages": []})
    assert out["intent"] == "general"


@pytest.mark.asyncio
async def test_query_reform_no_history_passthrough(stub_judge):
    """Empty history -> reform is a no-op; no LLM call is made."""
    stub = stub_judge([])
    out = await query_reform({"current_query": "BM25가 뭐야?", "messages": []})
    assert out["resolved_query"] == "BM25가 뭐야?"
    assert stub.calls == []


@pytest.mark.asyncio
async def test_query_reform_expands_followup(stub_judge):
    """Follow-up reference resolved using prior turn."""
    stub_judge(['{"reformed_query": "Elasticsearch RRF 설정 방법"}'])
    state = {
        "current_query": "어떻게 설정해?",
        "messages": [
            {"role": "user", "content": "Elasticsearch RRF가 뭐야?"},
            {"role": "assistant", "content": "RRF는 ..."},
            {"role": "user", "content": "어떻게 설정해?"},
        ],
    }
    out = await query_reform(state)
    assert "Elasticsearch RRF" in out["resolved_query"]
    assert "설정" in out["resolved_query"]


@pytest.mark.asyncio
async def test_query_reform_bare_topic_inherits_predicate(stub_judge):
    """Bare-topic ellipsis ("리밸런싱은?") should inherit the predicate from
    the prior turn so the search query is grammatically complete."""
    stub_judge(
        ['{"reformed_query": "Kafka consumer group 리밸런싱은 어떻게 동작해?"}']
    )
    state = {
        "current_query": "리밸런싱은?",
        "messages": [
            {"role": "user", "content": "Kafka consumer group 어떻게 동작해?"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "리밸런싱은?"},
        ],
    }
    out = await query_reform(state)
    assert "Kafka" in out["resolved_query"]
    assert "리밸런싱" in out["resolved_query"]


@pytest.mark.asyncio
async def test_query_reform_substitutes_demonstrative(stub_judge):
    """`그거` should be replaced with the concrete prior topic."""
    stub_judge(['{"reformed_query": "사내 ES 운영 표준 페이지 위치"}'])
    state = {
        "current_query": "그거 어디 있어?",
        "messages": [
            {"role": "user", "content": "사내 위키에 ES 운영 표준 페이지 있어?"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "그거 어디 있어?"},
        ],
    }
    out = await query_reform(state)
    assert "그거" not in out["resolved_query"]
    assert "ES" in out["resolved_query"] or "Elasticsearch" in out["resolved_query"]


@pytest.mark.asyncio
async def test_query_reform_topic_switch_keeps_current(stub_judge):
    """When the current question introduces a new topic with its own subject,
    the LLM should return it nearly unchanged — never fuse with prior topic."""
    stub_judge(['{"reformed_query": "CPU alert 설정 방법"}'])
    state = {
        "current_query": "CPU alert 설정은 어떻게 해?",
        "messages": [
            {"role": "user", "content": "Elasticsearch 설치 스크립트 작성해줘"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "CPU alert 설정은 어떻게 해?"},
        ],
    }
    out = await query_reform(state)
    assert "설치 스크립트" not in out["resolved_query"]


@pytest.mark.asyncio
async def test_query_reform_falls_back_to_current_on_empty(stub_judge):
    """If LLM returns empty reformed_query, fall back to current_query."""
    stub_judge(['{"reformed_query": ""}'])
    state = {
        "current_query": "어떻게?",
        "messages": [
            {"role": "user", "content": "Kafka는?"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "어떻게?"},
        ],
    }
    out = await query_reform(state)
    assert out["resolved_query"] == "어떻게?"


@pytest.mark.asyncio
async def test_query_decompose_single(stub_judge):
    stub_judge(['{"sub_queries": ["Elasticsearch RRF 동작 원리"]}'])
    state = {"resolved_query": "ES RRF 어떻게 동작?", "intent": "question"}
    out = await query_decompose(state)
    assert len(out["sub_queries"]) == 1


@pytest.mark.asyncio
async def test_query_decompose_multi(stub_judge):
    stub_judge(['{"sub_queries": ["A", "B", "C", "D"]}'])
    state = {"resolved_query": "X", "intent": "question"}
    out = await query_decompose(state)
    # capped at 3
    assert len(out["sub_queries"]) == 3


@pytest.mark.asyncio
async def test_query_decompose_skipped_for_chitchat(stub_judge):
    stub_judge([])  # should not be called
    out = await query_decompose({"resolved_query": "안녕", "intent": "chitchat"})
    assert out["sub_queries"] == []


@pytest.mark.asyncio
async def test_query_rewrite_parallel(stub_judge):
    stub_judge(
        [
            '{"keywords": "Elasticsearch RRF reciprocal rank fusion", "semantic": "mechanism of Reciprocal Rank Fusion in Elasticsearch"}',
            '{"keywords": "Kafka consumer group", "semantic": "definition of Kafka consumer group"}',
        ]
    )
    state = {
        "sub_queries": ["RRF 어떻게?", "kafka cg"],
        "target_indices_per_query": [["elasticsearch_docs"], ["kafka_docs"]],
    }
    out = await query_rewrite(state)
    plans = out["search_plans"]
    assert len(plans) == 2
    assert plans[0]["index"] == "elasticsearch_docs"
    assert plans[1]["index"] == "kafka_docs"
    # BM25 = keywords-only English for English-corpus indices
    assert "Elasticsearch" in plans[0]["bm25"]
    assert "RRF" in plans[0]["bm25"]
    # Semantic = full English natural form
    assert "Reciprocal Rank Fusion" in plans[0]["semantic"]


@pytest.mark.asyncio
async def test_query_rewrite_fans_out_per_routed_index(stub_judge):
    """A single sub-query routed to two indices yields two plans, one per index."""
    stub_judge(
        [
            '{"keywords": "Elasticsearch cluster operations", "semantic": "Elasticsearch cluster operations guide"}',
            '{"keywords": "Elasticsearch 클러스터 운영 가이드", "semantic": "Elasticsearch 클러스터 운영 가이드 절차"}',
        ]
    )
    state = {
        "sub_queries": ["ES 클러스터 운영"],
        "target_indices_per_query": [["elasticsearch_docs", "confluence_docs"]],
    }
    out = await query_rewrite(state)
    plans = out["search_plans"]
    assert len(plans) == 2
    assert {p["index"] for p in plans} == {"elasticsearch_docs", "confluence_docs"}
    # Both plans share the same sub_query_idx (the single sub-query at index 0)
    assert {p["sub_query_idx"] for p in plans} == {0}
    # Confluence plan keeps Korean BM25; ES plan stays English
    by_idx = {p["index"]: p for p in plans}
    assert "클러스터" in by_idx["confluence_docs"]["bm25"]
    assert "Elasticsearch" in by_idx["elasticsearch_docs"]["bm25"]
    assert "cluster" in by_idx["elasticsearch_docs"]["bm25"].lower()


@pytest.mark.asyncio
async def test_metadata_extract_with_filter(stub_judge):
    stub_judge(['{"source": ["elasticsearch"], "category": null, "date_range": {"gte": "2024-01-01"}}'])
    out = await metadata_extract({"resolved_query": "최근 ES 문서", "intent": "question"})
    f = out["metadata_filters"]
    assert f["source"] == ["elasticsearch"]
    assert "category" not in f  # null dropped
    assert f["date_range"] == {"gte": "2024-01-01"}


@pytest.mark.asyncio
async def test_index_route_per_subquery(stub_judge):
    stub_judge(
        [
            '{"indices": ["elasticsearch"]}',
            '{"indices": ["kafka"]}',
        ]
    )
    out = await index_route(
        {
            "sub_queries": ["ES RRF 동작", "Kafka consumer group"],
            "intent": "question",
        }
    )
    assert out["target_indices_per_query"] == [
        ["elasticsearch_docs"],
        ["kafka_docs"],
    ]


@pytest.mark.asyncio
async def test_index_route_picks_both_for_one_subquery(stub_judge):
    stub_judge(['{"indices": ["elasticsearch", "kafka"]}'])
    out = await index_route(
        {"sub_queries": ["ES와 Kafka 비교"], "intent": "question"}
    )
    assert len(out["target_indices_per_query"]) == 1
    assert set(out["target_indices_per_query"][0]) == {
        "elasticsearch_docs",
        "kafka_docs",
    }


@pytest.mark.asyncio
async def test_index_route_empty_falls_back_to_all(stub_judge):
    stub_judge(['{"indices": []}'])
    out = await index_route(
        {"sub_queries": ["모호한 질문"], "intent": "question"}
    )
    assert set(out["target_indices_per_query"][0]) == {
        "elasticsearch_docs",
        "kafka_docs",
        "confluence_docs",
    }


@pytest.mark.asyncio
async def test_index_route_invalid_falls_back(stub_judge):
    stub_judge(['{"indices": ["fake_index"]}'])
    out = await index_route({"sub_queries": ["x"], "intent": "question"})
    assert set(out["target_indices_per_query"][0]) == {
        "elasticsearch_docs",
        "kafka_docs",
        "confluence_docs",
    }


@pytest.mark.asyncio
async def test_index_route_no_subqueries(stub_judge):
    stub_judge([])  # not called
    out = await index_route({"sub_queries": [], "intent": "question"})
    assert out["target_indices_per_query"] == []


@pytest.mark.asyncio
async def test_index_route_internal_term_forces_confluence(stub_judge):
    """Organisation-internal terms must always include confluence_docs even if
    the LLM picks something else. Belt-and-braces over the LLM."""
    # LLM hallucinates: routes the internal term to elasticsearch (it does not know the
    # term). Our deterministic override must add confluence_docs.
    stub_judge(['{"indices": ["elasticsearch"]}'])
    out = await index_route(
        {"sub_queries": [f"{INTERNAL_TERM} 사용법"], "intent": "question"}
    )
    assert set(out["target_indices_per_query"][0]) == {
        "elasticsearch_docs",
        "confluence_docs",
    }


@pytest.mark.asyncio
async def test_index_route_internal_path_namespace(stub_judge):
    """Internal path namespaces route to confluence even when the LLM would
    otherwise pick only public indices. The prefix is read from the active
    terms file for the same reason as INTERNAL_TERM above."""
    namespace = internal_terms.load_terms()["namespaces"][0]
    stub_judge(['{"indices": ["elasticsearch"]}'])
    out = await index_route(
        {"sub_queries": [f"{namespace} 인덱스 설정"], "intent": "question"}
    )
    assert "confluence_docs" in out["target_indices_per_query"][0]


@pytest.mark.asyncio
async def test_index_route_internal_term_no_duplicate_confluence(stub_judge):
    """When the LLM already picks confluence, the override must NOT duplicate
    it — set semantics, not list-append."""
    org = internal_terms.load_terms()["org"][0]
    stub_judge(['{"indices": ["confluence"]}'])
    out = await index_route(
        {"sub_queries": [f"{org} 운영 가이드"], "intent": "question"}
    )
    assert out["target_indices_per_query"][0].count("confluence_docs") == 1


@pytest.mark.asyncio
async def test_query_analyze_internal_term_overrides_general(stub_judge):
    """Sentences that contain only an organisation-internal term and no other
    domain word (e.g., "acmesearch가 뭐야?") must still go to the search path."""
    stub_judge(['{"intent": "general"}'])
    out = await query_analyze(
        {"current_query": f"{INTERNAL_TERM}가 뭐야?", "messages": []}
    )
    assert out["intent"] == "question"


@pytest.mark.asyncio
async def test_hybrid_retrieve_merges_dedupes(stub_es):
    stub_es(
        [
            [{"id": "a", "title": "A", "url": "u/a", "content": "..."}],
            [
                {"id": "a", "title": "A", "url": "u/a", "content": "..."},
                {"id": "b", "title": "B", "url": "u/b", "content": "..."},
            ],
        ]
    )
    out = await hybrid_retrieve(
        {
            "search_plans": [
                {
                    "sub_query_idx": 0,
                    "sub_query": "q1",
                    "index": "elasticsearch_docs",
                    "bm25": "q1",
                    "semantic": "q1",
                },
                {
                    "sub_query_idx": 1,
                    "sub_query": "q2",
                    "index": "kafka_docs",
                    "bm25": "q2",
                    "semantic": "q2",
                },
            ],
            "metadata_filters": {},
            "intent": "question",
        }
    )
    ids = {d["id"] for d in out["candidates"]}
    assert ids == {"a", "b"}


@pytest.mark.asyncio
async def test_hybrid_retrieve_skips_when_no_plans(stub_es):
    stub_es([[]])
    out = await hybrid_retrieve(
        {
            "search_plans": [],
            "intent": "question",
        }
    )
    assert out["candidates"] == []


@pytest.mark.asyncio
async def test_hybrid_retrieve_uses_per_plan_index(monkeypatch):
    captured: list[tuple[str, str, list[str]]] = []

    async def fake_search(
        *, bm25_query_text, semantic_query_text=None, indices, metadata_filters=None, **kw
    ):
        captured.append((bm25_query_text, semantic_query_text, list(indices)))
        return [
            {
                "id": bm25_query_text,
                "title": "T",
                "url": "u/" + bm25_query_text,
                "content": "c",
            }
        ]

    from app.graph.nodes import hybrid_retrieve as hr_mod

    monkeypatch.setattr(hr_mod, "hybrid_search", fake_search)

    out = await hybrid_retrieve(
        {
            "search_plans": [
                {
                    "sub_query_idx": 0,
                    "sub_query": "es q",
                    "index": "elasticsearch_docs",
                    "bm25": "es q",
                    "semantic": "es semantic",
                },
                {
                    "sub_query_idx": 1,
                    "sub_query": "kafka q",
                    "index": "kafka_docs",
                    "bm25": "kafka q",
                    "semantic": "kafka semantic",
                },
            ],
            "metadata_filters": {},
            "intent": "question",
        }
    )
    assert sorted(captured) == [
        ("es q", "es semantic", ["elasticsearch_docs"]),
        ("kafka q", "kafka semantic", ["kafka_docs"]),
    ]
    assert {d["id"] for d in out["candidates"]} == {"es q", "kafka q"}


@pytest.mark.asyncio
async def test_self_check_sufficient(stub_judge):
    stub_judge(['{"sufficient": true, "reason": "OK"}'])
    out = await self_check(
        {
            "resolved_query": "x",
            "candidates": [{"id": "a", "title": "A", "url": "u", "content": "c"}],
            "retry_count": 0,
            "intent": "question",
        }
    )
    assert out["sufficient"] is True
    assert "retry_count" not in out


@pytest.mark.asyncio
async def test_self_check_insufficient_increments_retry(stub_judge):
    stub_judge(['{"sufficient": false, "reason": "off-topic"}'])
    out = await self_check(
        {
            "resolved_query": "x",
            "candidates": [{"id": "a", "title": "A", "url": "u", "content": "c"}],
            "retry_count": 0,
            "intent": "question",
        }
    )
    assert out["sufficient"] is False
    assert out["retry_count"] == 1


@pytest.mark.asyncio
async def test_self_check_no_candidates(stub_judge):
    stub_judge([])  # not called
    out = await self_check(
        {"resolved_query": "x", "candidates": [], "retry_count": 0, "intent": "question"}
    )
    assert out["sufficient"] is False
    assert out["retry_count"] == 1


def test_should_retry_branches():
    assert should_retry({"sufficient": True}) == "generate"
    assert should_retry({"sufficient": False, "retry_count": 0}) == "retry"
    # Budget is len(retrieval_top_k_schedule) — the last in-budget attempt
    # still routes to 'retry'.
    assert should_retry({"sufficient": False, "retry_count": 2}) == "retry"
    # When the retry budget is exhausted without sufficient evidence, route to
    # generate (which emits the soft-escape redirect). Domain questions MUST
    # stay grounded in the ES corpus and never fall back to general_chat.
    assert should_retry({"sufficient": False, "retry_count": 3}) == "generate"
    assert should_retry({"sufficient": False, "retry_count": 99}) == "generate"


@pytest.mark.asyncio
async def test_generate_with_docs(stub_generator):
    stub_generator(["답변 본문 [1] 입니다."])
    out = await generate(
        {
            "intent": "question",
            "resolved_query": "x",
            "candidates": [{"id": "a", "title": "A", "url": "u/a", "content": "c"}],
            "sufficient": True,
        }
    )
    assert "답변" in out["final_answer"]
    assert out["sources"] == [{"url": "u/a", "title": "A"}]


@pytest.mark.asyncio
async def test_generate_without_sufficient_calls_llm_with_no_sources(stub_generator):
    # Insufficient evidence no longer short-circuits to a cold one-liner —
    # generate calls the LLM so the GENERATE prompt's soft-escape rule can
    # produce a warm redirect. Sources stay empty (nothing grounded to cite).
    stub_generator(["혹시 이런 걸로 검색해볼까요?\n- 키워드"])
    out = await generate(
        {
            "intent": "question",
            "resolved_query": "x",
            "candidates": [{"id": "a"}],
            "sufficient": False,
        }
    )
    assert "검색해볼까요" in out["final_answer"]
    assert out["sources"] == []


@pytest.mark.asyncio
async def test_generate_chitchat(stub_generator):
    stub_generator(["안녕하세요. 사내 ES/Kafka 문서 질의응답을 돕습니다."])
    out = await generate({"intent": "chitchat", "resolved_query": "hi"})
    assert "안녕" in out["final_answer"]
    assert out["sources"] == []


# ---- debug_explain ----


@pytest.mark.asyncio
async def test_debug_explain_no_user_id_returns_guidance(stub_generator):
    """Without user_id we cannot fetch per-user logs — guide the user."""
    stub_generator([])  # not called
    from app.graph.nodes.debug_explain import debug_explain

    out = await debug_explain(
        {"intent": "debugging", "current_query": "왜 답변이 이렇게 나왔어?", "user_id": ""}
    )
    assert "user_id" in out["final_answer"]
    assert out["sources"] == []


@pytest.mark.asyncio
async def test_debug_explain_no_session_id_returns_guidance(stub_generator):
    """user_id present but session_id missing — refuse to mix prior threads."""
    stub_generator([])  # not called
    from app.graph.nodes.debug_explain import debug_explain

    out = await debug_explain(
        {
            "intent": "debugging",
            "current_query": "왜?",
            "user_id": "alice",
            "session_id": "",
        }
    )
    assert "session_id" in out["final_answer"]
    assert out["sources"] == []


@pytest.mark.asyncio
async def test_debug_explain_no_logs_returns_no_history_message(
    monkeypatch, stub_generator
):
    """When the user has no stored turns, return a helpful explanation."""
    stub_generator([])  # not called

    async def empty_fetch(user_id, *, session_id="", n=3, client=None):
        return []

    from app.graph.nodes import debug_explain as debug_explain_mod

    monkeypatch.setattr(debug_explain_mod, "fetch_recent_turns", empty_fetch)

    out = await debug_explain_mod.debug_explain(
        {
            "intent": "debugging",
            "current_query": "왜?",
            "user_id": "alice",
            "session_id": "sess-1",
        }
    )
    assert "현재 세션" in out["final_answer"]


@pytest.mark.asyncio
async def test_debug_explain_uses_recent_turns_in_prompt(
    monkeypatch, stub_generator
):
    """The 3 most recent turns are rendered into the prompt and the LLM's
    response is returned as the final answer."""
    canned_turns = [
        {
            "question": "Kafka 토픽 파티션 동작?",
            "intent": "question",
            "search_intent": "lookup",
            "sub_queries": ["Kafka 토픽 파티션"],
            "target_indices": ["kafka_docs"],
            "search_plans": [
                {
                    "sub_query": "Kafka 토픽 파티션",
                    "index": "kafka_docs",
                    "bm25": "Kafka topic partition",
                    "semantic": "Kafka topic partitions",
                }
            ],
            "sufficient": True,
            "sufficiency_reason": "kafka 자료 충분",
            "final_answer": "토픽은 파티션으로 나뉘어... [1]",
            "sources": [{"url": "u1", "title": "Kafka Topic"}],
            "progress_log": "🔍 질문 분석 중... (intent=question)",
        }
    ]

    async def fake_fetch(user_id, *, session_id="", n=3, client=None):
        assert user_id == "alice"
        assert session_id == "sess-1"
        return canned_turns

    from app.graph.nodes import debug_explain as debug_explain_mod

    monkeypatch.setattr(debug_explain_mod, "fetch_recent_turns", fake_fetch)

    stub = stub_generator(["방금 Kafka 토픽 답변 [Turn 1]은 kafka_docs에서 ..."])

    out = await debug_explain_mod.debug_explain(
        {
            "intent": "debugging",
            "current_query": "왜 그렇게 답했어?",
            "user_id": "alice",
            "session_id": "sess-1",
        }
    )
    assert "Turn 1" in out["final_answer"]
    # The prompt sent to the LLM must contain the rendered trace fields.
    sent_prompt = stub.calls[0][0].content  # HumanMessage content
    assert "Kafka 토픽 파티션 동작?" in sent_prompt
    assert "kafka_docs" in sent_prompt
    assert "kafka 자료 충분" in sent_prompt


@pytest.mark.asyncio
async def test_groundedness_check_returns_empty_when_no_citations(stub_judge):
    """No citations in answer (chitchat / general / 정보 없음) → skip check."""
    from app.graph.post_check import run_groundedness_check

    stub = stub_judge([])  # never called
    result = await run_groundedness_check(
        answer="안녕하세요!",
        candidates=[{"id": "1", "title": "x", "content": "y"}],
        cited_indices=set(),
    )
    assert result == {}
    assert stub.calls == []


@pytest.mark.asyncio
async def test_groundedness_check_aggregates_per_claim(stub_judge):
    """Verdict + score derived from per-claim supported flags."""
    from app.graph.post_check import run_groundedness_check

    stub_judge(
        [
            '{"grounded": false, "score": 0.5, "claims": ['
            '{"claim": "A", "citations": [1], "supported": true, "reason": "ok"},'
            '{"claim": "B", "citations": [2], "supported": false, "reason": "missing"}'
            "]}"
        ]
    )
    result = await run_groundedness_check(
        answer="...A [1] ... B [2]",
        candidates=[
            {"id": "1", "title": "Doc A", "content": "A is true"},
            {"id": "2", "title": "Doc B", "content": "C is true"},
        ],
        cited_indices={1, 2},
    )
    assert result["total_claims"] == 2
    assert result["supported_count"] == 1
    assert result["score"] == 0.5
    assert result["grounded"] is False
    assert len(result["claims"]) == 2


def test_groundedness_progress_renders_unsupported_claims():
    from app.graph.post_check import format_groundedness_progress

    msg = format_groundedness_progress(
        {
            "grounded": False,
            "score": 0.5,
            "supported_count": 1,
            "total_claims": 2,
            "claims": [
                {"claim": "A", "citations": [1], "supported": True, "reason": "ok"},
                {"claim": "B claim", "citations": [2], "supported": False, "reason": "no source"},
            ],
        }
    )
    assert "1/2" in msg
    assert "B claim" in msg
    assert "no source" in msg


# ---- query_analyze: instruction intent ----


@pytest.mark.asyncio
async def test_query_analyze_instruction_intent(stub_judge):
    """Style/tone directives reach the instruction branch, not search."""
    stub_judge(['{"intent": "instruction"}'])
    state = {"current_query": "앞으로 답변은 마크다운으로 해줘", "messages": []}
    out = await query_analyze(state)
    assert out["intent"] == "instruction"


@pytest.mark.asyncio
async def test_query_analyze_instruction_with_domain_word_preserved(stub_judge):
    """Override 2 only forces `question` for chitchat/general — instruction
    must survive even when the directive mentions Kafka/ES."""
    stub_judge(['{"intent": "instruction"}'])
    state = {
        "current_query": "Kafka 답변할 때는 영어 용어 그대로 써줘",
        "messages": [],
    }
    out = await query_analyze(state)
    assert out["intent"] == "instruction"


# ---- instruction_save ----


@pytest.mark.asyncio
async def test_instruction_save_no_user_id_skips_persistence(stub_generator):
    """Anonymous users still get a friendly reply but nothing is saved."""
    stub_generator([])  # not called
    from app.graph.nodes.instruction_save import instruction_save

    out = await instruction_save(
        {"current_query": "친근한 말투로 대답해", "user_id": ""}
    )
    assert "✅" in out["final_answer"]
    assert "기억하지 못" in out["final_answer"]
    assert out["sources"] == []


@pytest.mark.asyncio
async def test_instruction_save_persists_and_replies(
    monkeypatch, stub_judge, stub_generator
):
    """Happy path: judge LLM rewrites the md, store is upserted, generator
    LLM produces the confirmation reply."""
    stub_judge(["# 사용자 지침\n- 친근한 말투로 답변"])
    stub_generator(["✅ 앞으로 친근한 말투로 답변하도록 기억해 둘게요."])

    captured: dict = {}

    async def fake_get(user_id, *, client=None):
        return ""

    async def fake_update(user_id, md, *, client=None):
        captured["user_id"] = user_id
        captured["md"] = md

    from app.graph.nodes import instruction_save as mod

    monkeypatch.setattr(mod, "get_user_md", fake_get)
    monkeypatch.setattr(mod, "update_user_md", fake_update)

    out = await mod.instruction_save(
        {"current_query": "친근한 말투로 대답해", "user_id": "alice"}
    )

    assert captured["user_id"] == "alice"
    assert "친근한 말투" in captured["md"]
    assert "✅" in out["final_answer"]
    assert out[PROGRESS_KEY].startswith("📝")


@pytest.mark.asyncio
async def test_instruction_save_falls_back_to_existing_when_merge_blank(
    monkeypatch, stub_judge, stub_generator
):
    """If the merge LLM returns nothing, keep the existing md instead of
    wiping it."""
    stub_judge([""])  # blank merge output
    stub_generator(["✅ 처리되었습니다."])

    captured: dict = {}

    async def fake_get(user_id, *, client=None):
        return "# 사용자 지침\n- 기존 항목"

    async def fake_update(user_id, md, *, client=None):
        captured["md"] = md

    from app.graph.nodes import instruction_save as mod

    monkeypatch.setattr(mod, "get_user_md", fake_get)
    monkeypatch.setattr(mod, "update_user_md", fake_update)

    await mod.instruction_save(
        {"current_query": "이건 어떻게 처리될까", "user_id": "bob"}
    )
    assert captured["md"] == "# 사용자 지침\n- 기존 항목"


@pytest.mark.asyncio
async def test_generate_injects_user_md_block(monkeypatch, stub_generator):
    """When a user has saved instructions, the generate prompt includes a
    `[사용자 지침]` block so the LLM follows them."""
    stub = stub_generator(["답변 본문 [1]"])

    async def fake_get(user_id, *, client=None):
        return "# 사용자 지침\n- 항상 한 문단으로"

    from app.graph.nodes import generate as gen_mod

    monkeypatch.setattr(gen_mod, "get_user_md", fake_get)

    state = {
        "intent": "question",
        "current_query": "RRF는?",
        "resolved_query": "RRF는?",
        "user_id": "carol",
        "candidates": [{"id": "1", "title": "T", "url": "u", "content": "c"}],
        "sufficient": True,
    }
    out = await gen_mod.generate(state)
    assert out["final_answer"] == "답변 본문 [1]"
    sent_prompt = stub.calls[0][0].content
    assert "[사용자 지침]" in sent_prompt
    assert "한 문단으로" in sent_prompt


@pytest.mark.asyncio
async def test_generate_omits_block_when_no_user_md(
    monkeypatch, stub_generator
):
    """No saved md → no leading block in the prompt."""
    stub = stub_generator(["답변 [1]"])

    async def fake_get(user_id, *, client=None):
        return ""

    from app.graph.nodes import generate as gen_mod

    monkeypatch.setattr(gen_mod, "get_user_md", fake_get)
    state = {
        "intent": "question",
        "current_query": "Q?",
        "resolved_query": "Q?",
        "user_id": "",
        "candidates": [{"id": "1", "title": "T", "url": "u", "content": "c"}],
        "sufficient": True,
    }
    await gen_mod.generate(state)
    sent_prompt = stub.calls[0][0].content
    # The prompt template *mentions* `[사용자 지침]` in its rules text, but the
    # actual injected block (newline-prefixed) must be absent when there's
    # no saved md. The block format is "\n[사용자 지침]\n{md}\n".
    assert "\n[사용자 지침]\n" not in sent_prompt


# ---------- re_search intent detection (LLM-driven) ----------
#
# Classification is now the LLM's responsibility — no regex post-check.
# These tests cover the data plumbing (LLM → state) and defensive validation
# of the LLM's `forced_indices` payload. The semantic accuracy of when to
# emit re_search is a prompt-quality concern and is not unit-tested here.


@pytest.mark.asyncio
async def test_query_analyze_re_search_passes_forced_indices_through(stub_judge):
    """LLM returns re_search + canonical forced_indices → both surface intact."""
    stub_judge(['{"intent": "re_search", "forced_indices": ["confluence"]}'])
    out = await query_analyze(
        {"current_query": "confluence에서 검색해줘", "messages": []}
    )
    assert out["intent"] == "re_search"
    assert out["forced_indices"] == ["confluence"]


@pytest.mark.asyncio
async def test_query_analyze_re_search_multi_indices(stub_judge):
    """Multiple canonical aliases in LLM response → all preserved, order kept."""
    stub_judge(
        ['{"intent": "re_search", "forced_indices": ["elasticsearch", "kafka"]}']
    )
    out = await query_analyze(
        {"current_query": "공식 문서들 좀 뒤져봐줘", "messages": []}
    )
    assert out["intent"] == "re_search"
    assert out["forced_indices"] == ["elasticsearch", "kafka"]


@pytest.mark.asyncio
async def test_query_analyze_re_search_filters_invalid_aliases(stub_judge):
    """LLM emits canonical + garbage → garbage filtered, re_search stays."""
    stub_judge(
        ['{"intent": "re_search", "forced_indices": ["confluence", "garbage", "wiki"]}']
    )
    out = await query_analyze(
        {"current_query": "사내 위키에서 찾아봐", "messages": []}
    )
    assert out["intent"] == "re_search"
    assert out["forced_indices"] == ["confluence"]


@pytest.mark.asyncio
async def test_query_analyze_re_search_empty_indices_falls_back_to_question(stub_judge):
    """re_search with no valid destinations has nowhere to re-route — fall
    back to a normal question so the standard RAG path still answers."""
    stub_judge(['{"intent": "re_search", "forced_indices": []}'])
    out = await query_analyze(
        {"current_query": "다시 검색해줘", "messages": []}
    )
    assert out["intent"] == "question"
    assert "forced_indices" not in out


@pytest.mark.asyncio
async def test_query_analyze_re_search_all_invalid_falls_back_to_question(stub_judge):
    """forced_indices entirely outside the canonical set → empty after filter
    → fall back to question (same defensive path as empty list)."""
    stub_judge(
        ['{"intent": "re_search", "forced_indices": ["wiki", "garbage"]}']
    )
    out = await query_analyze(
        {"current_query": "wiki에서 찾아줘", "messages": []}
    )
    assert out["intent"] == "question"
    assert "forced_indices" not in out


@pytest.mark.asyncio
async def test_query_analyze_question_ignores_forced_indices(stub_judge):
    """forced_indices on a non-re_search intent is irrelevant — must not leak
    into the state (it would mis-route a normal question)."""
    stub_judge(['{"intent": "question", "forced_indices": ["confluence"]}'])
    out = await query_analyze(
        {"current_query": "Kafka 설정 찾아줘", "messages": []}
    )
    assert out["intent"] == "question"
    assert "forced_indices" not in out


@pytest.mark.asyncio
async def test_query_analyze_re_search_malformed_indices_field(stub_judge):
    """LLM returns non-list for forced_indices (string, null) → defensively
    treated as empty → fall back to question."""
    stub_judge(['{"intent": "re_search", "forced_indices": "confluence"}'])
    out = await query_analyze(
        {"current_query": "confluence에서 찾아줘", "messages": []}
    )
    assert out["intent"] == "question"
    assert "forced_indices" not in out


# ---------- re_search_setup node ----------

@pytest.mark.asyncio
async def test_re_search_setup_refuses_without_user_id(monkeypatch):
    from app.graph.nodes import re_search_setup as mod

    out = await mod.re_search_setup(
        {"forced_indices": ["confluence"], "user_id": "", "session_id": "s1"}
    )
    assert out["intent"] == "re_search"
    assert "user_id" in out["final_answer"]
    assert out["sufficient"] is False


@pytest.mark.asyncio
async def test_re_search_setup_refuses_without_session_id(monkeypatch):
    from app.graph.nodes import re_search_setup as mod

    out = await mod.re_search_setup(
        {"forced_indices": ["confluence"], "user_id": "u1", "session_id": ""}
    )
    assert "session_id" in out["final_answer"]


@pytest.mark.asyncio
async def test_re_search_setup_refuses_without_forced_indices(monkeypatch):
    from app.graph.nodes import re_search_setup as mod

    out = await mod.re_search_setup(
        {"forced_indices": [], "user_id": "u1", "session_id": "s1"}
    )
    assert "인덱스" in out["final_answer"]


@pytest.mark.asyncio
async def test_re_search_setup_refuses_when_no_prior_turn(monkeypatch):
    from app.graph.nodes import re_search_setup as mod

    async def fake_fetch(user_id, *, session_id, n, client=None):
        return []

    monkeypatch.setattr(mod, "fetch_recent_turns", fake_fetch)
    out = await mod.re_search_setup(
        {
            "forced_indices": ["confluence"],
            "user_id": "u1",
            "session_id": "s1",
        }
    )
    assert "직전" in out["final_answer"]


@pytest.mark.asyncio
async def test_re_search_setup_hands_off_to_rewrite_with_new_indices(
    monkeypatch,
):
    """re_search_setup populates sub_queries + target_indices_per_query for
    each forced index, then hands off to query_rewrite (does NOT reuse the
    prior turn's BM25/semantic strings — those were index-language-tuned)."""
    from app.graph.nodes import re_search_setup as mod

    prior_turn = {
        "intent": "question",
        "sub_queries": ["node exclude"],
        "search_plans": [
            {
                "sub_query_idx": 0,
                "sub_query": "node exclude",
                "index": "elasticsearch_docs",
                # English strings — these MUST NOT be reused when re-routing
                # to confluence_docs (Korean corpus).
                "bm25": "node exclude shard allocation",
                "semantic": "how to exclude a node",
            }
        ],
        "metadata_filters": {"source": "official"},
        "resolved_query": "노드 익스클루드 방법",
        "question": "노드 익스클루드 방법 알려줘",
    }

    async def fake_fetch(user_id, *, session_id, n, client=None):
        return [prior_turn]

    monkeypatch.setattr(mod, "fetch_recent_turns", fake_fetch)
    out = await mod.re_search_setup(
        {
            "forced_indices": ["confluence", "kafka"],
            "user_id": "u1",
            "session_id": "s1",
        }
    )
    # No intent overwrite — downstream nodes branch only on chitchat.
    assert "intent" not in out
    assert out["search_intent"] == "lookup"
    assert out["sub_queries"] == ["node exclude"]
    # target_indices_per_query is what query_rewrite (the next node) reads.
    assert out["target_indices_per_query"] == [
        ["confluence_docs", "kafka_docs"]
    ]
    # IMPORTANT: search_plans must NOT be set — query_rewrite will produce
    # them with fresh, index-language-aware BM25/semantic strings.
    assert "search_plans" not in out
    # metadata_filters & resolved_query are preserved verbatim.
    assert out["metadata_filters"] == {"source": "official"}
    assert out["resolved_query"] == "노드 익스클루드 방법"
    assert out["retry_count"] == 0


@pytest.mark.asyncio
async def test_re_search_setup_refuses_when_no_original_question_turn(
    monkeypatch,
):
    """Lookback contains only chitchat/instruction/re_search turns — no
    original `question` turn → refuse."""
    from app.graph.nodes import re_search_setup as mod

    async def fake_fetch(user_id, *, session_id, n, client=None):
        return [
            {"intent": "chitchat", "sub_queries": []},
            {"intent": "instruction", "sub_queries": []},
            # An incomplete re_search turn (no sub_queries saved)
            {"intent": "re_search", "sub_queries": []},
        ]

    monkeypatch.setattr(mod, "fetch_recent_turns", fake_fetch)
    out = await mod.re_search_setup(
        {
            "forced_indices": ["confluence"],
            "user_id": "u1",
            "session_id": "s1",
        }
    )
    assert "원본" in out["final_answer"]


@pytest.mark.asyncio
async def test_re_search_setup_walks_back_past_re_search_turns(monkeypatch):
    """A chain of re_search turns should always point back to the ORIGINAL
    question turn, not to the most recent re_search turn. Stable chaining."""
    from app.graph.nodes import re_search_setup as mod

    # Lookback newest-first: most recent two are re_search turns, then the
    # original question turn deeper in history.
    async def fake_fetch(user_id, *, session_id, n, client=None):
        return [
            {
                "intent": "re_search",
                "sub_queries": ["node exclude"],
                "metadata_filters": {},
                "resolved_query": "노드 익스클루드 방법",
            },
            {
                "intent": "re_search",
                "sub_queries": ["node exclude"],
                "metadata_filters": {},
                "resolved_query": "노드 익스클루드 방법",
            },
            {
                "intent": "question",
                "sub_queries": ["node exclude"],
                "metadata_filters": {"source": "official"},
                "resolved_query": "노드 익스클루드 방법",
                "question": "노드 익스클루드 방법 알려줘",
            },
        ]

    monkeypatch.setattr(mod, "fetch_recent_turns", fake_fetch)
    out = await mod.re_search_setup(
        {
            "forced_indices": ["elasticsearch"],
            "user_id": "u1",
            "session_id": "s1",
        }
    )
    # Walked past two re_search turns, found the question turn. Filters
    # come from the original turn (not the empty filters of the re_searches).
    assert out["sub_queries"] == ["node exclude"]
    assert out["metadata_filters"] == {"source": "official"}
    assert out["target_indices_per_query"] == [["elasticsearch_docs"]]


@pytest.mark.asyncio
async def test_re_search_setup_skips_when_top_turn_is_question_with_empty_subs(
    monkeypatch,
):
    """A question turn that somehow saved empty sub_queries should be
    skipped — keep walking until a usable question turn is found."""
    from app.graph.nodes import re_search_setup as mod

    async def fake_fetch(user_id, *, session_id, n, client=None):
        return [
            # Bad/empty question turn at the top
            {"intent": "question", "sub_queries": []},
            # Real question turn deeper
            {
                "intent": "question",
                "sub_queries": ["RRF"],
                "metadata_filters": {},
                "resolved_query": "RRF 동작",
            },
        ]

    monkeypatch.setattr(mod, "fetch_recent_turns", fake_fetch)
    out = await mod.re_search_setup(
        {
            "forced_indices": ["kafka"],
            "user_id": "u1",
            "session_id": "s1",
        }
    )
    assert out["sub_queries"] == ["RRF"]
    assert out["resolved_query"] == "RRF 동작"
