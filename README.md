# Hybrid RAG Chatbot

사내 문서를 검색해 **근거와 함께** 답하는 RAG 챗봇입니다. Elasticsearch 위에
BM25와 시맨틱 검색을 RRF로 합치고, 답변에 붙은 인용 번호는 실제로 검색된
문서를 가리킵니다.

핵심 아이디어 하나: **답변 품질은 생성이 아니라 검색에서 갈린다.** 그래서
질문 하나가 곧바로 검색으로 가지 않고 분해 → 인덱스 라우팅 → 재작성 →
검색 → 충분성 판정을 거치며, 근거가 부족하면 **각도를 바꿔 다시 검색**합니다.

구성:

- **FastAPI** — OpenAI 호환 API(`/v1/chat/completions`) + SSE 스트리밍
- **LangGraph** — 17개 노드로 이루어진 질의 처리 그래프
- **Elasticsearch** — BM25 + `semantic_text` 자동 임베딩, `retriever.rrf`로 융합
- **내장 채팅 UI** — `GET /`가 인라인 HTML을 서빙. 별도 프론트엔드 프로세스 없음
- **LLM** — 퍼블릭 OpenAI 또는 Azure 사내 게이트웨이. `LLM_PROVIDER`로 전환

## 빠른 시작

```bash
cd backend
uv sync --all-extras
cp .env.example .env                                          # [필수] 항목 채우기
cp app/internal_terms.example.json app/internal_terms.json    # 사내 용어 (아래 참조)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

브라우저로 `http://localhost:8000/` 접속. 로그인 카드에 아이디를 넣으면
`?user_id=<id>`가 붙고, 대화 로그와 답변 스타일 설정이 사용자별로 분리됩니다.

기동 후 진단:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

## 파이프라인

```
query_analyze  ─ 6-intent 분류
  ├─ chitchat    → generate
  ├─ general     → general_chat        (사내 문서 범위 밖 질문)
  ├─ debugging   → debug_explain       ("왜 그렇게 답했어?")
  ├─ instruction → instruction_save    ("앞으로는 짧게 답해줘")
  ├─ re_search   → re_search_setup     ("그거 말고 Confluence에서 찾아줘")
  └─ question    → query_reform → search_intent
                     ├─ count → es_count
                     ├─ list  → es_list
                     └─ lookup → query_decompose → index_route → query_rewrite
                                 → metadata_extract → hybrid_retrieve
                                 → self_check ─┬─ 충분 → generate (스트리밍)
                                               └─ 부족 → query_variate → 재검색
```

각 단계가 존재하는 이유:

- **`query_decompose`** — "ES와 Kafka 비교해줘"는 검색 쿼리가 아니라 두 개의
  검색과 한 번의 합성입니다. 비교·요약 같은 동사는 검색어에서 떨어져 나갑니다.
- **`index_route`** — sub-query마다 어느 인덱스를 볼지 따로 정합니다. 공식문서
  질문이 사내 위키를 긁지 않게 하고, 그 반대도 막습니다.
- **`query_rewrite`** — BM25용 키워드와 시맨틱용 명사구를 **따로** 만듭니다.
  RRF 안에서 두 retriever가 서로 다른 텍스트를 씁니다.
- **`self_check` → `query_variate`** — 근거가 부족하면 같은 질문을 반복하지
  않고 각도를 바꿉니다. `RETRIEVAL_TOP_K_SCHEDULE`을 따라 검색 폭도 넓힙니다.

## 사내 용어와 브랜딩

배포 환경마다 달라지는 두 가지는 소스가 아니라 설정에 있습니다.

**`backend/app/internal_terms.json`** — 사내에만 존재하는 고유명사 목록
(제품명·약어·사옥·네임스페이스). 질문에 이 단어가 등장하면 LLM 판정과 무관하게
사내 위키 인덱스를 검색 대상에 강제로 포함시킵니다. LLM은 한 회사 안에서만
쓰이는 단어를 알 수 없지만 사용자의 의도는 명확하기 때문입니다.

이 목록은 특정 조직을 지목하는 정보라 **저장소에 포함되지 않습니다.**
추적되는 것은 플레이스홀더인 `internal_terms.example.json` 뿐이고, 실제 파일이
없으면 예시 파일로 폴백합니다. 기동은 되지만 이 라우팅은 사실상 동작하지 않고,
기동 로그에 경고가 남습니다. 경로는 `INTERNAL_TERMS_FILE`로도 지정합니다.

반대로 "운영 중인", "장애 이력" 같은 **운영 상태 표현**은 어느 회사에서나 같은
뜻이므로 코드에 남아 있습니다. 이 구분이 설계의 핵심입니다.

**`CHATBOT_NAME`** — UI 제목·헤더·로그인 카드·인트로 문구와 잡담/일반대화
페르소나에 함께 쓰이는 표시 명칭. 기본값은 `사내 문서 챗봇`입니다.

## 환경 변수

`backend/.env.example` 참고. 자주 쓰는 것만:

| 변수 | 설명 |
|------|------|
| `LLM_PROVIDER` | `openai` (테스트) 또는 `azure` (사내 게이트웨이) |
| `OPENAI_API_KEY` / `HCHAT_API_KEY` | 선택한 프로바이더의 키 |
| `HCHAT_ENDPOINT` | 사내 게이트웨이 주소. **소스에 기본값 없음** — azure 사용 시 필수 |
| `ES_HOSTS` | 단일 또는 콤마 구분 멀티노드 |
| `ES_USERNAME` / `ES_PASSWORD` | Basic Auth |
| `RETRIEVAL_TOP_K_SCHEDULE` | 재검색 시도별 top_k. 리스트 길이가 곧 시도 예산 |
| `CHATBOT_NAME` | 표시 명칭 |
| `INTERNAL_TERMS_FILE` | 사내 용어 파일 경로 (선택) |

## API

- `GET /` — 내장 채팅 UI (HTML)
- `GET /info` — 서비스 메타데이터
- `GET /health` — ES 연결 · 인덱스 존재 · LLM 키 설정 진단
- `GET /v1/models` — OpenAI 호환
- `POST /v1/chat/completions` — OpenAI 호환 SSE 스트리밍

## 테스트

```bash
cd backend && uv run pytest -q
```

155개 중 154개 통과. `test_instruction_save_no_user_id_skips_persistence`는
기대 문자열과 구현이 어긋난 채로 남아 있는 알려진 실패입니다.

테스트는 사내 용어를 활성화된 파일에서 읽습니다. 그래서 용어를 설정한 배포에서는
실제 라우팅을 검증하고, 플레이스홀더만 있는 새 클론에서도 그대로 통과합니다.

## 문서

- `SPEC.md` — 9차에 걸친 설계 변경 이력과 현재 사양
- `backend/OPERATIONS.md` — 새 검색 인덱스 추가, 검색 쿼리 수정 런북
- `backend/README.md` — `.env` 항목별 채우기 가이드
