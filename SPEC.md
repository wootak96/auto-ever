# RAG 챗봇 프로젝트 SPEC

> **마지막 갱신: 2026-04-30 (9차).** 초기 SPEC 대비 변경 + 2~9차 라운드 보강. 자세한 내역은 각 섹션 참조.
>
> **1차 변경 (구조)**
> - 인덱스: `docs-*` 패턴 → 실제 인덱스 `elasticsearch_docs`, `kafka_docs` 두 개
> - 임베딩: ES `_inference`(`hchat-embedding`) → `semantic_text` 필드 자동 임베딩(`text-embedding-3-small`, 1536d)
> - 워크플로우: §3.4 채택. 리랭커(ES `text_similarity_reranker` / LLM 리랭크) 모두 **보류**
> - **per-sub-query 인덱스 라우팅** 추가 (`index_route` 노드)
> - LLM provider **스위치**: OpenAI(현재 테스트) / Azure(운영, 사내 게이트웨이) 양립
> - LLM API 키: `Authorization: Bearer <key>` 헤더로 per-request 오버라이드 가능
> - 프론트엔드: chatbot-ui(Next.js) → FastAPI **내장 인라인 HTML/JS** (`GET /`)
> - 배포: Docker Compose → uv 단독 실행 (Docker은 운영 전환 시 추가)
>
> **2차 변경 (실데이터 적합화 + UX)**
> - **실제 인덱스 매핑 확인**: `elasticsearch_docs`/`kafka_docs` 두 인덱스 모두 `content` + `content_embedding` 두 필드만 존재. `title`/`url`/`source`/`category`/`updated_at` 부재 (사용자가 추후 인덱스 보강 예정)
> - **BM25 단일 필드 fallback**: `ES_FIELD_TITLE`이 비어 있으면 `multi_match`(title^2, content) → `match(content)` 단일 필드. 빈 `_source` 필드는 projection에서 자동 제외
> - **`metadata_extract` 프롬프트 강화**: 사용자가 명시적 제약을 표현했을 때만 추출. 토픽 단어로 `source` 자동 매핑 금지 (도메인 라우팅은 `index_route`가 담당). 미존재 필드 필터로 인한 0건 hit 방지
> - **`query_decompose` 프롬프트 교체**: Anthropic-style 영문 프롬프트 + 예시 (Microsoft/Google, France) + JSON 출력 강제 블록
> - **UI 진행 메시지에 결과 동봉**: 분해 결과를 트리(`├─`/`└─`)로, 재작성 결과를 `before  →  after`로 진행 영역에 표시
> - **출처 렌더링 안전장치**: `url`이 비어 있는 항목은 출처 섹션에서 자동 제외 (dangling `[1] ` 방지)
> - **로그인 게이트** (URL 파라미터 기반): `GET /` 접근 시 `?user_id=<id>` 없으면 로그인 카드 표시. 로그인 후 `?user_id=<id>` 부착 + user_id별 대화 분리 저장
> - 테스트: provider-aware fallback (`active_api_key`) 비교로 수정 → 57/57 통과
>
> **3차 변경 (브랜딩 + 4-intent 라우팅 + UI 테마)**
> - **챗봇 브랜딩**: 모든 표시 명칭을 **"사내 문서 챗봇"(`CHATBOT_NAME` 설정값)**으로 통일 (브라우저 title, 헤더, 로그인 카드, 빈 상태)
> - **로그인 인트로 메시지**: 로그인 직후 빈 채팅창에 어시스턴트 버블로 자동 표시 — *"안녕하세요 저는 사내 문서 챗봇입니다. 무엇을 도와드릴까요?"* (transient, `messages` 배열에 미포함 → 백엔드 전송 X)
> - **4-intent 라우팅**: `query_analyze` intent 확장 → `question` / `followup` / `chitchat` / **`general`** (도메인 외 일반 질문)
> - **새 노드 `general_chat`**: 사내 문서 도메인 밖 질문에 일반 LLM 지식으로 친절히 답변. 첫 줄에 *"ℹ️ 사내 문서 범위 밖의 질문이라 일반 지식으로 답변드릴게요."* 안내 후 본 답변. 토큰 스트리밍
> - **사이클 fallback**: `hybrid_retrieve ↔ self_check` 사이클이 retry 한도 도달 시 dead-end(`해당 정보를 찾을 수 없습니다`) 대신 **`general_chat`으로 graceful escape**
> - **`CHITCHAT` 프롬프트 개선**: 매번 역할 안내 반복 금지. 친근한 1~2문장. 정체성 질문(`넌 누구야?`)에만 짧은 소개
> - **UI 테마 전면 교체**: GitHub 다크 톤 → **iPhone/iMessage 라이트 테마** 고정 (시스템 다크모드 무시). 반투명 backdrop blur 네비, iMessage 그라디언트 버블, 원형 ↑ 송신 버튼, safe-area-inset 지원, ≤520px 모바일 반응형
> - 테스트: `should_retry` 한도 도달 시 `general_chat` 반환으로 갱신 → 57/57 통과
>
> **4차 변경 (이중 쿼리 재작성 + UI 최소화)**
> - **`QUERY_REWRITE` 이중 출력 + 영어화 + 명사구 강제**: 입력(한국어 가능) → JSON `{"keywords": ..., "semantic": ...}` 둘 다 **영어**. `keywords`는 BM25용 핵심어 2~6개, `semantic`은 **질문 의도를 유지하는 명사구 4~12 토큰** (예: "definition of Elasticsearch", "how Kafka consumer groups work"). 가상 답변(HyDE) 형태는 **명시적으로 금지**(예: "Elasticsearch is a distributed search engine ..." ✗). few-shot 5개 예시 + 안티-예시 1개
> - **state 확장**: `semantic_queries: list[str]` 병렬 필드 추가. `rewritten_queries[i]`(BM25 키워드)와 `semantic_queries[i]`(시맨틱 문장)는 같은 길이를 유지
> - **ES 클라이언트 시그니처 변경**: `build_rrf_query(bm25_query_text, semantic_query_text=None, ...)`, `hybrid_search(bm25_query_text=, semantic_query_text=, ...)`. semantic 미지정 시 BM25 텍스트로 폴백 → 단일 텍스트 호출자도 호환. ES `retriever.rrf` 안에서 BM25 retriever와 semantic retriever가 **다른 텍스트**를 사용
> - **`QUERY_DECOMPOSE` 사내 예시 추가**: `Elasticsearch와 Kafka 특징 비교해줘 → ["Elasticsearch 특징","Kafka 특징"]` 한국어 도메인 예시(예시 #3) 추가
> - **UI 최소화**:
>   - 헤더에서 `LLM API Key (선택)` 입력칸 제거 (서버는 여전히 `Authorization: Bearer` 헤더를 받지만, 내장 UI는 이제 보내지 않음)
>   - 헤더의 `model: ... · indices: ...` 메타 표시 + `/info` fetch 제거
> - **답변 단계 진행 메시지 정리**: `generate`의 `✍️ 답변 생성 중...` (정상/근거 없음 두 케이스), `general_chat`의 `💡 일반 대화로 답변 중...` 모두 제거. 직전 노드(`self_check` / `query_analyze`) 메시지 후 바로 구분선 → 답변 본문 스트리밍
> - 테스트: 새 JSON 형태 (`keywords`/`semantic`) 반영 + ES 시그니처 변경 반영 → 58/58 통과
>
> **5차 변경 (인트로 메시지 타이핑 애니메이션)**
> - **로그인 인트로 스트리밍**: 기존 즉시 표시 → **타이프라이터 효과**로 한 글자씩 출력 (`STEP_MS=35ms`, `START_MS=250ms` 초기 지연)
> - **안전한 취소 로직**: `introTimer` 핸들로 setTimeout 체인 관리. 사용자가 스트림 도중 첫 메시지를 보내거나 "대화 초기화"를 누르면 `cancelIntroStream()`이 즉시 타이머 해제 + DOM 노드 dereference (detached 노드에 텍스트 append 방지)
> - **첫 메시지 전송 시 인트로 완전 제거**: `chat.innerHTML = ''`로 인트로 버블 제거 → 대화 영역 위에 인트로가 쌓이지 않음 (3차 동작 유지, 5차에서 취소 안전성만 보강)
> - **5.1차 인트로 영구 표시 전환**: 첫 메시지 전송 시 인트로를 **freeze**(스트림 강제 완성)하고 DOM에 그대로 유지. 이후 모든 대화는 인트로 아래에 누적. 페이지 새로고침/messages 존재 시 `renderIntroStatic()`으로 정적 즉시 표시.
>
> **6차 변경 (검색 의도 분기 + 도메인 grounding 강화)**
> - **검색 의도 분류 (`search_intent`) 신규**: `query_analyze`(intent) → `search_intent`(검색 형태) 2단 분류. 후보: `lookup` / `count` / `list`. LLM 분류(`SEARCH_INTENT_CLASSIFY` 프롬프트)
>   - `lookup` (기본) — 기존 RRF 경로 (decompose → rewrite → metadata → route → retrieve → check → generate)
>   - `count` — `es_count` 노드, `_count` API로 인덱스별 개수 즉시 반환 (LLM/임베딩 0회)
>   - `list` — `es_list` 노드, `terms` aggregation on `title` 필드. title 필드 부재 시 안내 메시지로 graceful fallback
> - **retry 시 쿼리 변형 (`query_variate` 노드 신규)**: `self_check`이 불충분 판정 후 retry 진입 시 같은 쿼리 반복 대신 **다른 각도로 재작성**. 전략: BROADEN / SYNONYMS / DIFFERENT ANGLE / ADD DOMAIN / DECOMPOSE FURTHER 5가지 중 LLM이 선택. 이전 쿼리와 동일 출력 금지 + 안전망(빈 출력 시 이전 값 재사용). 새 프롬프트 `QUERY_VARIATE`
> - **도메인 질문 안전망 (`query_analyze`)**: LLM이 비교 질문(`"Elasticsearch와 Kafka 비교해줘"`) 등을 `general`/`chitchat`으로 잘못 분류해도 정규식 `_DOMAIN_PATTERN`이 도메인 단어(elasticsearch/엘라스틱서치/kafka/카프카/RRF/BM25/semantic/시맨틱/kNN/consumer/topic/partition/broker/index/인덱스/shard/샤드/embedding/임베딩 등) 감지 시 **강제로 `question`으로 override**
> - **도메인 grounded-only 정책**: `should_retry`의 retry 소진 분기를 `general_chat` → `generate`로 변경. ES/Kafka 도메인 질문이 답이 없으면 일반 LLM 지식으로 폴백하지 않고 **"해당 정보를 찾을 수 없습니다"** 명시. `general_chat`은 이제 `general` intent 직행 경로로만 도달 (도메인 외 잡담 전용)
> - **출처 중복 버그 픽스**: `GENERATE` 프롬프트가 LLM에게 `**출처**` 섹션 작성을 지시 + 서버가 `render_sources()`로 또 추가 → 중복 발생. 프롬프트에서 `**출처**` 작성 금지 명시 + `chat.py`에 스트림 sanitizer 추가 (LLM이 어겨도 `**출처**` 발견 시 스트림 truncate, 멀티 chunk 분할 도착 안전 처리)
> - **`general` intent whitelist 누락 픽스**: `query_analyze.py`의 intent 검증에서 `general`이 빠져있어 LLM이 분류해도 `question`으로 강등되던 dead-code 버그 → whitelist에 추가
> - 테스트: 62/62 통과 (60 + 안전망 검증 2 + count/list path 2)
>
> **7차 변경 (intent 분류 ↔ 쿼리 재작성 분리, followup 제거)**
> - **`query_analyze` 단일책임화 (intent only)**: 기존에 한 노드가 "intent 분류 + history-aware resolved_query 생성"을 동시에 하던 구조에서, **분류만** 담당하도록 단순화. 출력은 `{"intent": "..."}` 한 필드
> - **`query_reform` 노드 신규**: history-aware self-contained 쿼리 재작성을 단일 책임으로 추출. search 분기(`question`)일 때만 진입. **history가 비어 있으면 LLM 호출 스킵 후 원문 통과** (첫 turn 비용 절감). 출력은 `resolved_query: str` (한국어 유지, 영어 번역은 후속 `query_rewrite`가 담당)
> - **`followup` intent 제거 (4-intent → 3-intent)**: `followup`은 `question`과 동일 검색 경로를 타며 라벨만 다른 dead distinction이었음. 멀티턴 후속 질문은 모두 `question`으로 분류한 뒤 `query_reform`이 history-aware로 펼침. `Intent = Literal["question", "chitchat", "general"]`
> - **워크플로우 변경**: `query_analyze` → (chitchat→generate / general→general_chat / **question→query_reform**) → `search_intent` → ... chitchat/general 경로는 `query_reform` 스킵, 다운스트림에서 `current_query`로 폴백
> - **프롬프트 분리**: `QUERY_ANALYZE`는 분류 규칙만 (도메인 단어/비교 질문 처리 유지). `QUERY_REFORM` 신설 — 지시어 치환 + 생략된 주어/목적어 복원, 4가지 예시(RRF 후속, consumer group 후속, 비교 후속, history 없음)
> - **다운스트림 노드 변경 없음**: `query_decompose`/`query_rewrite`/`metadata_extract`/`self_check`/`generate`/`general_chat` 등은 여전히 `resolved_query` 한 필드만 읽으므로 history 직접 주입 불필요. 멀티턴 의존성을 `query_reform` 한 곳에 집중
> - **ES `list_titles` 집계 필드 변경**: `terms` aggregation 대상이 `s.es_field_title` → `f"{s.es_field_title}.keyword"`. text 필드는 fielddata 없이 집계 불가 → `.keyword` 서브필드 사용이 표준
> - 테스트: 65/65 통과 (62 + query_reform 3개)
>
> **8차 변경 (Confluence 인덱스 추가 + 인덱스별 언어 정책 + 모든 프롬프트 영문화)**
> - **`confluence_docs` 인덱스 추가** (3번째 인덱스): 사내 Confluence 위키 한국어 코퍼스. 운영 가이드 / 회의록 / 장애 대응 / 인수인계 / 사내 표준·정책 / 팀 위키 등. 기술 용어는 영어, 나머지는 한국어로 작성된 사내 문서. `config.py`의 `index_alias_map`/`all_indices`에 `"confluence" → "confluence_docs"` 추가
> - **워크플로우 순서 변경 (`route → rewrite`)**: 기존 `decompose → rewrite → metadata → route → retrieve` → 신규 `decompose → index_route → query_rewrite → metadata_extract → hybrid_retrieve`. **rewrite는 라우팅된 인덱스의 언어 정책에 맞춰 출력해야 하므로 route가 먼저**. ES/Kafka 인덱스(영어 코퍼스)는 영어 BM25/semantic, Confluence 인덱스(한국어 코퍼스)는 한국어 BM25/semantic (기술용어는 영어 유지)
> - **`SearchPlan` state 도입 + sub-query × index fan-out**: 한 sub-query가 N개 인덱스에 라우팅되면 N개 search_plan으로 분해. 기존 `rewritten_queries`/`semantic_queries` 1차원 배열 폐기, 평탄화된 `search_plans: list[SearchPlan]`로 대체. 각 plan = `(sub_query_idx, sub_query, index, bm25, semantic)`. `hybrid_retrieve`/`query_variate`도 plan 단위로 동작
> - **`QUERY_REWRITE`/`QUERY_VARIATE` 인덱스별 언어 정책**: `{target_index}` 플레이스홀더 추가. `confluence_docs`이면 한국어 BM25 + 한국어 semantic noun phrase ("X 정의", "X 운영 가이드", "X 동작 원리" 등) 출력, 그 외(`elasticsearch_docs`/`kafka_docs`)는 영어 출력 ("definition of X", "how X works" 등). 두 정책 모두에서 기술용어(Elasticsearch, Kafka, RRF, BM25, kNN, consumer group 등)는 영어 유지
> - **`INDEX_ROUTE` 프롬프트 확장**: `"confluence"` 옵션 추가, 사내 운영 맥락(회의록/장애 대응/인수인계 등)이 함께 등장하면 공개 인덱스 + confluence 동시 라우팅 가이드 명시
> - **`QUERY_ANALYZE` 도메인 단어 리스트 + `_DOMAIN_PATTERN` 정규식 확장**: confluence 키워드 17종 추가 (`Confluence`, `컨플루언스`, `위키`, `wiki`, `회의록`, `미팅록`, `미팅 노트`, `운영 가이드/매뉴얼/절차`, `장애 대응/보고`, `인수 인계`, `사내 표준/정책/가이드/매뉴얼/절차`, `팀 위키`). 공백 변동 흡수(`\s*`). confluence-only 질문("회의록 보여줘", "운영 가이드 어디 있어?")이 LLM에서 `general` 오분류돼도 정규식 safety net이 `question`으로 강제 override
> - **모든 프롬프트의 prose를 영어로 전환** (예시 섹션은 한국어 입력 분포 유지). LLM이 영어 instruction을 더 안정적으로 따른다는 사용자 판단. 챗봇 출력 리터럴은 한국어 보존 ("해당 정보를 찾을 수 없습니다.", "사내 문서 챗봇"(`CHATBOT_NAME` 설정값) 정체성, "ℹ️ 사내 문서 범위 밖의 질문이라..." 헤더 등). `GENERATE`/`CHITCHAT`/`GENERAL_CHAT`은 첫 줄에 `Respond in Korean.` 명시. `QUERY_REFORM`은 출력이 한국어 문장이므로 "Output in Korean" 명시
> - **`CHITCHAT`/`GENERAL_CHAT` 정체성 갱신**: "Elasticsearch / Kafka 등" → "Elasticsearch / Kafka 공식문서 + Confluence 사내 위키"로 명시
> - **`workflow.py` SSE 직렬 정책 유지**: route/rewrite/metadata 구간은 데이터 의존성상 병렬화 가능하지만, 진행 메시지 race를 막기 위해 의도적 직렬 유지
> - 테스트: 71/71 통과 (65 + confluence fan-out 1 + per-index rewrite 1 + count 3-인덱스 1 + 도메인 패턴 confluence 2)
>
> **9차 변경 (per-user 채팅 로그 + 디버깅 intent)**
> - **`{user_id}_logs` 인덱스 도입 (per-user 채팅 로그)**: 로그인 사용자별 ES 인덱스 생성. 매 턴마다 질문/답변/intent/search_intent/sub_queries/target_indices/search_plans/candidates/sufficient/sources/progress_log(UI에 표시된 trace 그대로) 한 문서로 저장. 인덱스명은 `sanitize_user_id(user_id) + "_logs"` (lowercase + `[a-z0-9_-]`만 허용, 그 외는 `_`로 치환). 신규 서비스 모듈 `app/services/log_store.py` (sanitize / ensure_log_index / save_turn / fetch_recent_turns). 저장은 best-effort — ES 실패 시 warning 로그만 남기고 채팅 응답 흐름을 막지 않음
> - **4번째 intent `debugging` 추가**: 사용자가 직전 답변에 대해 "왜 이렇게 답했어?", "근거가 뭐야?", "방금 답변 어디서 가져왔어?" 같이 챗봇 자신의 응답을 메타 질의할 때 분류. `Intent = Literal["question", "chitchat", "general", "debugging"]`. `query_analyze`의 LLM 분류 + 정규식 safety net 양쪽으로 검출
> - **debug 정규식 (`_DEBUG_ANSWER_REF` + `_DEBUG_META_QUESTION` co-occurrence + `_DEBUG_STRONG`)**: 단어 순서 독립적인 검출 — "왜 답변이 이상해?" / "답변이 왜 이래?" / "왜 Kafka 답변이 이렇게 나왔어?" 모두 매칭. 도메인 단어가 포함돼도 메타 질의는 debugging이 우선 (사용자가 새 정보가 아니라 과거 답변에 대해 묻는 것이므로). 강한 standalone 패턴("디버깅", "왜 이렇게 판단했어", "근거가 뭐야") 따로 매칭
> - **신규 노드 `debug_explain`**: `{user_id}_logs`에서 최근 **3턴**을 시간 역순으로 가져와 `DEBUG_EXPLAIN` 프롬프트로 LLM에 전달. LLM이 사용자 질의가 어느 턴을 가리키는지 판단(주제·위치·일반 질의) → 해당 턴의 trace를 한국어로 설명. `[Turn 1]` (최신) / `[Turn 2]` / `[Turn 3]` 표기. user_id 미전송 시 / 로그 0건일 때 graceful 안내 메시지. generate / general_chat과 동일하게 토큰 스트리밍 (`on_chat_model_stream`)
> - **새 워크플로우 분기**: `query_analyze → debugging → debug_explain → END`. 검색 파이프라인 완전 우회 (decompose/route/rewrite/retrieve 모두 스킵)
> - **API 변경**: `ChatRequest`에 `user_id: str | None` 필드 추가, 프론트엔드(`web.py`)는 URL의 `user_id` 파라미터를 POST body에 동봉. `chat.py`가 streaming 중 progress message + LLM 응답 토큰을 누적 → SSE 종료 후 `save_turn(user_id, doc)` 호출 (debugging intent는 자기 자신을 로그에 안 남기도록 skip)
> - **`{user_id}_logs` 매핑**: `keyword`/`text`/`date`/`object` 혼합. `progress_log`는 텍스트로 저장(검색·디버깅 가시성). search_plans / candidates / sources는 nested object
> - 테스트: 95/95 통과 (71 + log_store 17 + debug intent 3 + debug_explain 3 + workflow debug path 1)

## 1. 프로젝트 개요

### 1.1 목적
사내 폐쇄망에서 운영되는 RAG 기반 챗봇. Elasticsearch에 인덱싱된 문서(Elasticsearch 공식문서, Kafka 공식문서 등)만을 참조하여 답변을 생성한다.

### 1.2 핵심 원칙
- **Grounded Answer Only**: Elasticsearch 검색 결과에 근거한 답변만 생성. 검색 결과에 없는 내용은 "모른다"고 답변한다.
- **출처 명시 필수**: 모든 답변에 인덱스의 `url` 필드를 인용한다.
- **단계별 투명성**: 각 파이프라인 단계를 UI에 스트리밍으로 노출한다.

### 1.3 배포 환경
- 사내 폐쇄망 VM 단독 호스팅
- 단일 호스트에서 `uvicorn` 직접 실행 (Docker는 운영 전환 시 도입)
- 외부 인터넷 접근 불가 (사내 게이트웨이 경유)
- 단계: 현재는 퍼블릭 OpenAI(`gpt-4o-mini` 등)로 개발/테스트, 추후 사내 Azure 게이트웨이(`gpt-5.4-mini`)로 전환

---

## 2. 시스템 아키텍처

```
┌──────────────────────┐      ┌──────────────────────────────┐      ┌─────────────────────┐
│  Browser             │      │        FastAPI Backend       │      │   Elasticsearch     │
│  (built-in chat UI)  │─────▶│  (OpenAI-Compatible Server)  │─────▶│   (사내 기존)        │
│  served at GET /     │ SSE  │                              │      │   semantic_text     │
│  inline HTML/JS      │◀─────│     ┌──────────────────┐     │      │   + BM25 + RRF      │
└──────────────────────┘      │     │   LangGraph      │     │      └─────────────────────┘
                              │     │   Workflow       │     │
                              │     └──────────────────┘     │      ┌─────────────────────┐
                              │              │               │─────▶│  LLM Provider 스위치 │
                              └──────────────┼───────────────┘      │  ├─ OpenAI (현재)    │
                                             │                      │  └─ Azure 사내 GW    │
                                             └──────────────────────│     (운영 전환용)     │
                                                                    └─────────────────────┘
```

### 2.1 컴포넌트

| 컴포넌트 | 역할 | 기술 스택 |
|---------|------|----------|
| Frontend | 채팅 UI | FastAPI 내장 인라인 HTML/JS (`app/api/web.py`, `GET /`). 외부 chatbot-ui 등도 SSE로 붙일 수 있음 |
| Backend | OpenAI 호환 API + RAG 파이프라인 | FastAPI, LangGraph, LangChain |
| Vector Store | 문서 검색 | Elasticsearch (`elasticsearch_docs`, `kafka_docs`) |
| LLM | 분석/판단/생성 | Provider 스위치 — `LLM_PROVIDER=openai`(테스트) / `azure`(운영) |
| Embedding | 쿼리/문서 임베딩 | ES `semantic_text` 필드 자동 처리 (`text-embedding-3-small`, 1536d) |

### 2.2 클라이언트 ↔ Backend 연동 방식

**선택: A — OpenAI 호환 프록시 서버 + 내장 UI**

- FastAPI로 `POST /v1/chat/completions` 엔드포인트를 구현하여 OpenAI API 스펙을 흉내낸다.
- 같은 서버가 `GET /`에서 내장 채팅 UI(인라인 HTML/CSS/JS)도 서빙. 별도 프론트 빌드 불필요.
- 외부 클라이언트(chatbot-ui 등)도 그대로 붙일 수 있음:
  ```
  OPENAI_API_HOST=http://<backend-host>:8000
  OPENAI_API_KEY=<dummy-or-real-key>
  ```
- LLM API 키 입력 경로 (둘 중 하나로 동작):
  - `Authorization: Bearer <key>` 헤더 (per-request 오버라이드, 내장 UI 상단 입력란이 이 경로)
  - `.env`의 `OPENAI_API_KEY` / `HCHAT_API_KEY` (헤더 미지정 또는 `dummy`/`dummy-key`/`placeholder` 같은 폼이면 폴백)
- 응답은 OpenAI SSE 포맷(`data: {...}\n\n`)으로 스트리밍.

---

## 3. 데이터 레이어 (Elasticsearch)

### 3.1 기본 전제
- 인덱스, 청크, 임베딩은 **이미 구축되어 있음** (본 프로젝트 범위 외)
- 쿼리 임베딩은 ES `semantic_text` 필드가 자동 처리

### 3.2 인덱스 구조

> 실제 인덱스명/필드명은 `.env`로 분리 (`ES_INDEX_ELASTICSEARCH`, `ES_INDEX_KAFKA`, `ES_INDEX_CONFLUENCE`, `ES_FIELD_*`).

#### (a) 현재 운영 매핑 (실측, 2026-04-26 / 8차에서 confluence_docs 추가)

```yaml
indices:
  - elasticsearch_docs   # 50 chunks (BBQ HNSW, dot_product) — 영어 코퍼스 (ES 공식 docs)
  - kafka_docs           # 50 chunks                          — 영어 코퍼스 (Kafka 공식 docs)
  - confluence_docs      # 8차 신규                            — 한국어 코퍼스 (사내 Confluence 위키:
                                                             #   운영 가이드 / 회의록 / 장애 대응 /
                                                             #   인수인계 / 사내 표준·정책 / 팀 위키)

fields (현재 존재):
  content:           text (copy_to: content_embedding)
  content_embedding: semantic_text
                     inference: openai-embeddings-small (text-embedding-3-small, 1536d, dot_product)
                     chunking: word strategy, max_chunk_size=250, overlap=50
                     index_options: bbq_hnsw (m=16, ef_construction=100, oversample=3.0)

fields (부재 — 추후 보강 예정):
  title, url, source, category, updated_at
```

#### (b) 목표 매핑 (사용자가 추후 보강)

```yaml
fields:
  title:             text (analyzer: korean_mixed)
  content:           text (analyzer: korean_mixed)
  content_embedding: semantic_text (inference: text-embedding-3-small, 1536d)
  url:               keyword  # 답변 인용에 사용
  source:            keyword  # elasticsearch | kafka
  category:          keyword
  updated_at:        date
```

> 백엔드는 부재 필드에 대해 자동으로 안전 동작:
> - `ES_FIELD_TITLE=`(빈 값)이면 BM25는 `match(content)` 단일 필드만 사용
> - `_source` projection에서 빈 필드는 제외
> - `url`이 비어 있는 항목은 답변 출처 섹션에서 자동 제외

### 3.3 검색 전략

#### (1) 하이브리드 검색 (BM25 + semantic + RRF)
- BM25 (입력: 영어 키워드 2~6개, `query_rewrite`의 `keywords`):
  - `ES_FIELD_TITLE`이 설정되면: `multi_match`로 `title^2`, `content`
  - `ES_FIELD_TITLE`이 비면 (현재 운영 기본값): `match(content)` 단일 필드
- semantic (입력: 영어 자연 문장, `query_rewrite`의 `semantic`): `content_embedding` (semantic_text 필드, ES가 자동 임베딩 + kNN)
- 결합: ES 8.14+ `retriever.rrf` DSL — `rank_window_size=50`, `rank_constant=60`. **하나의 RRF 요청 안에서 BM25 retriever와 semantic retriever가 서로 다른 입력 텍스트를 사용**
- 초기 후보 수(`RETRIEVAL_TOP_K`): 10건

#### (2) 인덱스 라우팅 (per-sub-query, 8차에서 confluence 추가)
- `index_route` 노드가 **각 sub-query마다** 어느 인덱스(`elasticsearch_docs` / `kafka_docs` / `confluence_docs` / 그 조합)를 검색할지 LLM에 질의
- 8차 변경: 라우팅이 **`query_rewrite`보다 먼저 실행**됨. rewrite가 라우팅된 인덱스의 언어 정책에 따라 출력해야 하기 때문
- `hybrid_retrieve`는 `search_plans` (sub-query × routed-index 페어로 평탄화)를 받아 plan별로 단일 인덱스 검색 → 결과를 `id`/`url` 기준 merge + dedup
- 도메인 키워드가 전혀 없는 메타 질의(예: "전체 문서 몇 개?")는 LLM 호출 없이 **모든 인덱스로 short-circuit**
- LLM 응답이 비어 있거나 파싱 실패 시 **모든 인덱스** 검색으로 안전 폴백

#### (3) 메타데이터 필터링
- LangGraph의 `metadata_extract` 노드에서 쿼리로부터 필터 조건 추출 (현재 전역 1회)
- 추출 가능 필드: `source`, `category`, `updated_at` (기간)
- 필터는 RRF retriever 안의 `bool.must` / `bool.filter`로 적용
- **추출 정책 (보수적)**: 사용자가 명시적으로 제약을 표현했을 때만 추출. 단순히 질문 토픽이 elasticsearch/kafka라는 이유로 `source`를 채우지 않음. 도메인 라우팅은 별도의 `index_route` 노드가 처리. 이 정책은 미존재 필드 필터로 인한 0건 hit를 막기 위한 안전장치이기도 함.

#### (4) 리랭커 (보류)
- 현 단계 미적용. 필요 시 ES `text_similarity_reranker` retriever를 같은 요청 안에 묶거나, 별도 LLM 리랭크 노드를 추가한다 (M10).

---

## 3.4 RAG 파이프라인 상세 프로세스 (질의 → 참조 문서 결정)

### Step 1. 질의 의도 분석 (Query Understanding) — 7차에서 두 노드로 분리
- **Step 1a. `query_analyze`** (LLM 1회): 3-intent 분류 (`question` / `chitchat` / `general`). intent만 출력, 쿼리 재작성 없음
- **Step 1b. `query_reform`** (LLM 0~1회, search 분기일 때만): 멀티턴 컨텍스트를 반영해 `resolved_query`를 한국어 self-contained 한 문장으로 생성. **history 비어 있으면 LLM 호출 스킵 후 원문 통과**
- chitchat → 바로 `generate`로 점프 (CHITCHAT 응답). general → `general_chat`. question → `query_reform` → search 파이프라인

### Step 2. Query Decompose
- 단일/다중 질의 판별 + decompose
- 단일이면 `[resolved_query]` 그대로, 다중이면 독립 sub-query 리스트 (1~3개)

**출력**: `sub_queries: list[str]`

### Step 3. Index Route (sub-query별) — 8차에서 rewrite보다 먼저
- 각 sub-query마다 `elasticsearch_docs` / `kafka_docs` / `confluence_docs` / 그 조합 중에서 LLM이 선택
- 8차 변경: rewrite보다 **먼저** 실행. rewrite가 인덱스 언어 정책에 따라 출력해야 하기 때문
- **출력**: `target_indices_per_query: list[list[str]]` (sub-query 순서와 매칭)
- 도메인 키워드 부재 시 LLM 호출 생략하고 모든 인덱스로 short-circuit (`route_query` 헬퍼)

### Step 4. Query Rewrite (sub-query × routed-index, 인덱스별 언어 정책)
8차에서 fan-out 구조로 변경: 한 sub-query가 N개 인덱스에 라우팅되면 **N개의 search_plan**으로 분해. 각 plan은 라우팅된 인덱스의 언어 정책에 맞춰 BM25/semantic을 출력.

**인덱스별 언어 정책**:
- `elasticsearch_docs` / `kafka_docs` (영어 코퍼스): **영어 BM25 + 영어 semantic** (기존 정책)
- `confluence_docs` (한국어 코퍼스): **한국어 BM25 + 한국어 semantic**. 단 기술용어(Elasticsearch, Kafka, RRF, BM25, kNN, consumer group, broker, partition, mapping, dense_vector 등)는 영어 그대로 유지 — 한국 엔지니어가 사내 문서를 작성할 때 따르는 관행

**출력 필드 (각 plan마다)**:
- **`bm25`** — BM25 lexical 검색용. 핵심어 2~6개. 약어 정규화 (ES→Elasticsearch, K8s→Kubernetes), stopword/구두점 제거 (영어/한국어 양쪽 stopword 정의)
- **`semantic`** — `semantic_text` 벡터 검색용. **질문 의도를 유지하는 명사구** 4~12 토큰
  - 영어 허용 형태: `"definition of X"`, `"mechanism of X"`, `"X performance tuning"`, `"how X works"`
  - 한국어 허용 형태: `"X 정의"`, `"X 동작 원리"`, `"X 성능 튜닝"`, `"X 운영 가이드"`, `"X 절차"`
  - **가상 답변(HyDE) 형식 금지** — 완성된 평서문 (영: *"X is …"*, 한: *"X는 …이다"*) 출력 X. 환각된 답변이 검색을 오염시키지 않도록 질문결 보존

- **합성 동사(synthesis verb) 금지 원칙**: `비교/차이/대비/vs/요약/정리/번역` (compare/difference/contrast/summarize/translate)은 **검색 대상이 아니라 LLM이 답변 생성 단계에서 수행하는 작업**. `query_decompose`가 토픽별로 분해 후 `query_rewrite`는 동사를 떼고 토픽 단위로만 재작성. `"differences between X and Y"`, `"comparison of X and Y"`, `"X와 Y 비교"` 같은 비교 명사구는 **검색 쿼리로 출력 금지** — 비교 문서가 코퍼스에 따로 있을 가능성이 낮고, 있어도 토픽별 검색 결과를 LLM이 합성하는 게 원칙

**출력**: `search_plans: list[SearchPlan]`. 각 plan = `{sub_query_idx, sub_query, index, bm25, semantic}`
**한쪽 누락 시**: 다른 쪽 값으로 폴백. 둘 다 누락 시 원본 sub-query로 폴백 (검색 항상 동작)

### Step 5. Metadata Extract (전역 1회)
- 쿼리에서 `source` / `category` / `date_range` 등 필터 조건 추출

### Step 6. Hybrid Retrieval (search_plan별 병렬)
각 search_plan에 대해 (BM25 키워드, semantic 문장, 단일 인덱스) 트리플로 ES에서 한 번의 RRF 요청 수행:
- **키워드 검색**: BM25 (`title^2`, `content`) ← `plan.bm25` (인덱스 언어 정책에 따라 영어/한국어)
- **의미 검색**: `semantic_text` 필드 자동 임베딩 + kNN ← `plan.semantic`
- **RRF**로 결합 → 상위 후보 N건 (plan별)

ES 8.14+ `retriever.rrf` 한 요청으로 끝남:

```
retriever.rrf(
  retrievers=[bm25, semantic],
  rank_window_size=50,
  rank_constant=60
)
```

전체 sub-query 결과를 **union → `id`/`url` 기준 dedup**.

### Step 7. Reranking (보류)
현 단계 미적용. 필요 시 ES `text_similarity_reranker`를 retriever 안에 묶거나 별도 LLM 리랭크 노드를 추가.

### Step 8. Self-Check (LLM 충분성 판단)
- 후보가 비어 있으면 LLM 호출 없이 즉시 `sufficient=False`로 단락(short-circuit) 후 retry
- 후보가 있으면 LLM이 원본 질의 기준으로 충분성을 판단:
  - 충분 → answer generation
  - 불충분 + 재시도 < `RETRIEVAL_MAX_RETRY` → 다시 retrieve
  - 불충분 + 재시도 한도 도달 → "해당 정보를 찾을 수 없습니다" 메시지로 generate

### Step 9. Generate
- 통과한 문서들 + 대화 히스토리를 컨텍스트로 답변 생성 (스트리밍)
- 본문에 `[1]`, `[2]` 인용 번호 + 하단 `**출처**` 섹션

---

## 4. LangGraph 워크플로우

### 4.1 전체 플로우

```
START
  │
  ▼
[1] query_analyze     ─── 4-intent 분류 (question/chitchat/general/debugging) + 도메인·debug 안전망 (9차: debugging 추가)
  │
  ├─ chitchat ──────────────────────────────────────────▶ [10] generate (CHITCHAT) ──▶ END
  │
  ├─ general  ──────────────────────────────────────────▶ [11] general_chat ──▶ END
  │
  ├─ debugging ─────────────────────────────────────────▶ [12] debug_explain ({user_id}_logs 최근 3턴 분석) ──▶ END
  │
  ▼ question (search)
[1b] query_reform     ─── history-aware self-contained 재작성 (7차 신규, history 없으면 LLM 스킵)
  │
  ▼
[2] search_intent     ─── 검색 형태 분류 (lookup / count / list, LLM)
  │
  ├─ count ─▶ [8] es_count   ─── _count API 즉시 반환 (LLM/임베딩 0회) ──▶ END
  │
  ├─ list  ─▶ [9] es_list    ─── terms agg on title (title 필드 부재 시 안내) ──▶ END
  │
  ▼ lookup
[3] query_decompose   ─── 복합 쿼리 → 서브쿼리 분해 (1~3개)
  │
  ▼
[4] index_route       ─── 서브쿼리별 elasticsearch_docs / kafka_docs / confluence_docs / 조합 결정 (8차: rewrite보다 먼저)
  │
  ▼
[5] query_rewrite     ─── (sub-query × routed-index)별 fan-out → search_plans
                          ES/Kafka 인덱스: 영어 BM25 + 영어 semantic
                          confluence 인덱스: 한국어 BM25 + 한국어 semantic (기술용어는 영어 유지)
  │
  ▼
[6] metadata_extract  ─── 필터 조건(source/category/date_range) 추출 (전역, 보수적)
  │
  ▼
[7] hybrid_retrieve ◀──────────────┐ (cycle: 재시도)
  │                                │
  ▼                                │
[7a] self_check                    │ ─── 후보 충분성 판단 (비어 있으면 LLM 없이 short-circuit)
  │                                │
  ├─ 불충분 + retry < MAX ─▶ query_variate ──┘ (쿼리 다른 각도로 재작성)
  │
  ├─ 불충분 + retry ≥ MAX ─▶ [10] generate ("해당 정보를 찾을 수 없습니다.") ──▶ END
  │
  ▼ 충분
[10] generate         ─── RAG-grounded 답변 생성 (출처 포함, 스트리밍)
  │
  ▼
END
```

핵심 사이클: **`hybrid_retrieve ↔ self_check ↔ query_variate`**가 `RETRIEVAL_MAX_RETRY`회 돌면서 매 retry마다 쿼리를 다른 각도로 변형. 끝까지 못 찾으면 `general_chat`이 아닌 `generate`로 가서 "해당 정보를 찾을 수 없습니다" 응답 (도메인 grounded-only).

> 리랭커 노드는 의도적으로 제외 (M12에서 필요 시 도입).

### 4.2 노드별 상세

#### [1] query_analyze (7차에서 intent 분류만 담당하도록 단순화)
- **입력**: 현재 질문 + 이전 대화 히스토리 (history는 후속 질문이 도메인 주제에 의존하는지 판단하는 용도로만 사용)
- **출력**: `{intent: "question|chitchat|general"}` — **resolved_query는 더 이상 여기서 생성하지 않음 (7차)**
- **역할 — 3-intent 분류 (7차)**:
  - `question`: ES/Kafka 도메인 정보 요청 (도메인 단어 보임 OR 직전 대화의 도메인 주제 후속). **두 도메인 비교 질문도 무조건 question**
  - `chitchat`: 인사·감사·챗봇 정체성 질문 (검색 불필요)
  - `general`: 도메인 단어가 1개도 없고 직전 대화도 도메인 주제가 아닌 완전 무관한 질문 → `general_chat` 직행
- **7차 변경 — followup 제거**: 기존 4-intent의 `followup`은 `question`과 동일 경로를 타던 dead distinction이라 제거. 멀티턴 후속도 모두 `question`으로 분류한 뒤 다음 노드(`query_reform`)가 history-aware로 펼침
- **6차 도메인 안전망 + 8차 confluence 확장**: LLM이 잘못 분류해도 `_DOMAIN_PATTERN` 정규식이 도메인 단어 검출 시 `general`/`chitchat` → `question`으로 강제 override. 두 그룹으로 구성:
  - Public-tech: elasticsearch/엘라스틱서치/kafka/카프카/RRF/BM25/semantic/시맨틱/kNN/consumer/topic/partition/broker/index/인덱스/shard/샤드/embedding/임베딩 등
  - Internal-wiki (8차 추가): confluence/컨플루언스/위키/wiki/회의록/미팅록/미팅 노트/운영 가이드/운영 매뉴얼/운영 절차/장애 대응/장애 보고/인수 인계/사내 표준/사내 정책/사내 가이드/사내 매뉴얼/사내 절차/팀 위키 (공백 변동 흡수: `\s*`)
- **UI 표시**: `🔍 질문 분석 중... (intent=...)`

#### [1b] query_reform (7차 신규, search 분기 전용)
- **언제 호출되나?**: `query_analyze`가 `question`으로 분류한 경우에만. `chitchat`/`general` 경로는 스킵 (다운스트림에서 `current_query`로 폴백)
- **입력**: 현재 질문 + 이전 대화 히스토리
- **출력**: `{resolved_query: str}` — 한국어 self-contained 한 문장
- **역할**:
  - 지시어("그게", "어떻게", "그러면", "더 자세히")를 직전 주제로 치환
  - 생략된 주어/목적어를 히스토리에서 끌어와 명시
  - 새로운 정보를 추가하지 않음 (검색 가능한 정도까지만 펼치기)
  - 한국어 유지 — 영어 번역은 후속 `query_rewrite`가 담당
- **방어 로직 — history 빈 경우 LLM 호출 스킵**: 첫 턴(history empty)에는 펼칠 대상이 없으므로 LLM을 호출하지 않고 `current_query`를 그대로 통과 → 비용 절감
- **방어 로직 — 빈 응답 폴백**: LLM이 빈 `reformed_query`를 반환하면 `current_query`로 폴백
- **프롬프트 (`QUERY_REFORM`)**: 4개 예시 — RRF 후속질문("어떻게 설정해?" → "Elasticsearch RRF 설정 방법"), consumer group 후속("리밸런싱은?" → "Kafka consumer group 리밸런싱 동작 원리"), 비교 후속("둘 중 어떤 게 나아?" → "Elasticsearch와 Kafka 중 어떤 것이 더 적합한지"), history 없는 경우(원문 그대로)
- **UI 표시**: `📝 쿼리 재작성... (<reformed>)` 또는 `📝 쿼리 재작성... (히스토리 없음, 원문 사용)`

#### [2] search_intent (6차 신규)
- **입력**: `resolved_query`
- **출력**: `{search_intent: "lookup|count|list"}`
- **역할**: ES 질의 형태를 분류해 적절한 노드로 라우팅. LLM 분류(`SEARCH_INTENT_CLASSIFY`)
  - `lookup`: 문서 내용 검색 → 기존 RRF 경로
  - `count`: 문서 개수 조회 → `es_count` 직행
  - `list`: 문서 목록 조회 → `es_list` 직행
- **폴백**: 잘못된 값 / 빈 응답 시 `lookup`
- **UI 표시**: `🎯 검색 유형 분석... (문서 내용 검색|문서 개수 조회|문서 목록 조회)`

#### [2] query_decompose
- **입력**: `resolved_query`
- **출력**: `sub_queries: list[str]` (1~3개)
- **역할**: 복합 질문 분해 (예: "Elasticsearch와 Kafka의 차이점" → 2개 sub-query)
- **프롬프트**: Anthropic-style 영문 (Microsoft/Google, France 예시 2개) + JSON 출력 강제 (`{"sub_queries": [...]}`)
- **UI 표시** (실제 결과 동봉):
  ```
  🧩 질의 분해 중... (2개 서브쿼리)
     ├─ How much profit did Microsoft make last year?
     └─ How much profit did Google make last year?
  ```

#### [3] query_rewrite (4차: 이중 출력 / 8차: 인덱스별 fan-out + 언어 정책)
- **입력**: `sub_queries` + `target_indices_per_query` (8차: index_route가 먼저 실행되므로 routing 결과 보유)
- **처리**: 각 sub-query를 라우팅된 인덱스 수만큼 fan-out → (sub_query × index) 페어로 LLM 호출 병렬 실행
  - 호출 시 프롬프트에 `{target_index}` 주입 → LLM이 해당 인덱스 언어 정책으로 출력
  - 한 sub-query가 1개 인덱스에 라우팅되면 plan 1개, N개 인덱스에 라우팅되면 plan N개
- **출력**: `search_plans: list[SearchPlan]`. 각 plan = `{sub_query_idx, sub_query, index, bm25, semantic}`
- **인덱스별 언어 정책 (8차)**:
  - `elasticsearch_docs` / `kafka_docs`: 영어 BM25 + 영어 semantic
  - `confluence_docs`: 한국어 BM25 + 한국어 semantic (기술용어는 영어 유지)
- **프롬프트**: `QUERY_REWRITE` — JSON `{"keywords": "...", "semantic": "..."}`. few-shot 9개 (ES RRF, Kafka cg, ES kNN, ES features, Kafka cg 정리, ES 정의, **confluence 운영 가이드/장애 대응/회의록 3개 추가**)
- **폴백**: 한쪽 비면 다른쪽으로 채우고, 둘 다 비면 원본 sub-query로 폴백
- **UI 표시** (인덱스 + BM25/semantic 모두 노출):
  ```
  ✏️ 검색 쿼리 최적화 중...
     ├─ [elasticsearch_docs] ES 클러스터 운영
     │     • BM25:     Elasticsearch cluster operations
     │     • semantic: Elasticsearch cluster operations guide
     └─ [confluence_docs] ES 클러스터 운영
           • BM25:     Elasticsearch 클러스터 운영 가이드
           • semantic: Elasticsearch 클러스터 운영 절차
  ```

#### [4] metadata_extract
- **입력**: `resolved_query`
- **출력**: `metadata_filters` (예시 아래)
- **역할**: 쿼리에서 필터 조건 추출 (현재 전역 1회)
  ```json
  {
    "source": ["elasticsearch", "kafka"],
    "category": null,
    "date_range": {"gte": "2024-01-01"}
  }
  ```
- **UI 표시**: 진행 메시지 inline

#### [5] index_route (8차: rewrite보다 먼저 실행)
- **입력**: `sub_queries` (8차: rewrite가 아직 실행 안 됐으므로 원문 sub-query 사용)
- **출력**: `target_indices_per_query: list[list[str]]` — sub-query 순서와 매칭
- **역할**: 각 서브쿼리마다 LLM에게 어느 인덱스에 검색할지 질의 (`asyncio.gather`로 병렬). 응답이 비어 있거나 파싱 실패 시 모든 인덱스로 안전 폴백. 도메인 키워드 부재 메타 질의는 LLM 호출 없이 모든 인덱스로 short-circuit (`route_query` 헬퍼)
- **인덱스 description (`INDEX_ROUTE` 프롬프트)**:
  - `elasticsearch`: Elasticsearch 공식문서. 검색/색인/RRF/kNN/매핑, **8 ~ 9 버전 트러블슈팅**, **업그레이드 가이드(8.x → 9.x 마이그레이션)**, **REST API 레퍼런스** 등
  - `kafka`: Apache Kafka 공식문서, 토픽/파티션/컨슈머/프로듀서/스트림즈, **Kafka KIP**, **릴리스 노트**, **JIRA 이슈 트래커**, **Sarama Go 클라이언트**, **Confluent Schema Registry**, **librdkafka C 클라이언트**, **Amazon MSK 개발자 가이드** 등
  - `confluence` (8차 신규): 사내 Confluence 위키 — **사내 운영 가이드 / 회의록 / 장애 대응 / 인수인계 / 사내 표준·정책 / 팀 위키 / 사내 프로젝트 메모 / 한국어로 작성된 운영·관리 문서** 등. ES/Kafka 같은 기술 토픽이라도 "사내 운영", "회의록", "인수인계" 같은 사내 맥락이 함께 등장하면 confluence + 해당 공개 인덱스 동시 라우팅
- **UI 표시**: `🧭 인덱스 라우팅: <alias 요약>`

#### [6] hybrid_retrieve (8차: search_plan 단위)
- **입력**: `search_plans`, `metadata_filters`
- **처리**: 각 plan에 대해 단일 인덱스로 `hybrid_search(bm25_query_text=plan.bm25, semantic_query_text=plan.semantic, indices=[plan.index])` 한 번의 RRF 요청. `asyncio.gather`로 병렬 실행 후 결과 merge + `id`/`url` dedup
- **출력**: `candidates: list[Document]` (`RETRIEVAL_TOP_K * len(search_plans)` 상한 내)
- **UI 표시**: `📚 Knowledge Base 검색 중.. (N건 발견)` + 가져온 문서 `title` 목록 (중복 제거, `• title` 형태). 디버깅 편의를 위해 `title` 필드만 노출

#### [7] self_check (6차에서 fallback 정책 변경)
- **입력**: `resolved_query` + `candidates`
- **출력**: `{sufficient: bool, reason: str}` + `retry_count` 증가 (불충분 시)
- **분기 (`should_retry`)**:
  - 충분 → `generate`
  - 불충분 + retry < `RETRIEVAL_MAX_RETRY` → **`query_variate`** → `hybrid_retrieve` 재실행 (6차: 변형 노드 삽입)
  - 불충분 + retry 한도 도달 → **`generate`** ("해당 정보를 찾을 수 없습니다."). 6차에서 `general_chat` 폴백 제거 — 도메인 grounded-only 정책: ES 코퍼스에 답이 없으면 일반 LLM 지식으로 폴백 안 함
- **단락**: candidates 비어 있으면 LLM 호출 없이 즉시 `sufficient=False`, `retry_count += 1`
- **합성 쿼리 충분성 원칙**: 원본 질문에 비교/차이/요약/번역 같은 합성 동사가 포함된 경우, 충분성은 **각 토픽별 근거 유무**로 판단. "두 토픽을 직접 비교한 단일 문서"의 부재는 불충분 사유가 아님 — 합성은 답변 단계 LLM이 수행. (예: "ES와 Kafka 비교"에서 ES 특징 문서 + Kafka 특징 문서가 모두 있으면 sufficient=true)
- **개별 문서 vs 전체 충분성**: 전체 `sufficient`는 **토픽 커버리지** 기준 (개별 문서 무관도 OR 합산 아님). 개별 문서가 무관해도 다른 문서가 토픽을 커버하면 전체 sufficient=true. 한편 LLM이 `per_doc` 배열로 각 문서 관련성도 판정해 UI에 노출 (디버깅용).
- **UI 표시**: `🔎 검색 결과 검증 중... ✓ 충분|✗ 불충분` + 문서별 ✓/✗ + `title` 목록 (제목 단위 dedup, 동일 title의 여러 chunk 중 하나라도 relevant면 ✓로 집계)

#### [7b] query_variate (6차 신규 / 8차: search_plan 단위 + 인덱스 언어 정책 보존)
- **언제 호출되나?**: `self_check` 불충분 + retry 한도 미도달 시 `hybrid_retrieve` 직전에 끼어듦 (`retry_count > 0`일 때만 의미)
- **입력**: 이전 `search_plans` + `sufficiency_reason` + `retry_count`
- **출력**: 새 `search_plans` (각 plan의 `bm25`/`semantic`만 변형, `sub_query_idx`/`sub_query`/`index`는 보존)
- **인덱스 언어 정책 보존 (8차)**: 프롬프트에 `{target_index}` 주입 → 변형 후에도 같은 인덱스의 언어 정책 유지 (영어 plan은 영어로 변형, 한국어 plan은 한국어로 변형)
- **프롬프트 (`QUERY_VARIATE`)**: 5가지 전략 명시 + 합성 동사 금지 원칙
  - **BROADEN**: 너무 구체적인 단어 제거, 일반 개념으로
  - **SYNONYMS**: 동의어/별칭으로 치환
  - **DIFFERENT ANGLE**: **같은 토픽의** 다른 측면(사용 사례·설정·내부동작·아키텍처·성능). cross-entity 비교는 금지
  - **ADD DOMAIN CONTEXT**: 누락된 `Elasticsearch`/`Kafka` 도메인 단어 보강
  - **DECOMPOSE FURTHER**: 긴 쿼리에서 핵심 1개 추출
  - **합성 동사 금지(`QUERY_REWRITE`와 동일 원칙)**: 비교/차이/요약/번역/정리 등은 검색 대상이 아님. 입력 sub-query가 (decompose 누수로) 두 엔티티를 담고 있어도 첫번째/주요 엔티티 1개만 검색. 출력에서 `"differences between X and Y"`, `"comparison of X and Y"`, `"X vs Y"` 형태 절대 금지
- **방어 로직**: 변형 결과가 이전과 동일/빈 값이면 이전 값 재사용 → 루프 안전
- **UI 표시**:
  ```
  🔄 검색 쿼리 변형 (재시도 1회차) — <reason>
     └─ BM25:     Kafka consumer group  →  Kafka consumer group rebalance
        semantic: definition of Kafka consumer group  →  how Kafka consumer groups rebalance partitions
  ```

#### [8] es_count (6차 신규, count 검색 의도 전용)
- **입력**: 없음 (search_intent에서 분기됨)
- **출력**: `final_answer: "📊 사내 문서 통계 — 총 N건\n- elasticsearch_docs: A건\n- kafka_docs: B건"`, `sources=[]`
- **처리**: 모든 인덱스에 대해 `_count` API 호출. LLM 호출 없음. 임베딩 호출 없음.
- **UI 표시**: `📊 문서 개수 조회 중... (총 N건)`

#### [9] es_list (6차 신규, list 검색 의도 전용)
- **입력**: 없음
- **출력**: `final_answer: "📚 문서 목록 — 총 N개 제목\n**elasticsearch_docs** (M개)\n- title1 (chunks)\n..."`, `sources=[]`
- **처리**: `terms` aggregation on `s.es_field_title` (현재 .env에서 비어 있으면 graceful fallback)
- **현재 매핑 한계**: `ES_FIELD_TITLE`이 빈 값이면 *"현재 인덱스에 `title` 필드가 매핑되어 있지 않아 문서 목록을 표시할 수 없습니다"* 안내. 인덱스에 `title` 필드 보강 후 `ES_FIELD_TITLE=title` 설정하면 즉시 동작
- **UI 표시**: `📚 문서 목록 조회 중... (N개 제목)`

#### [10] generate (6차에서 출처 정책 변경)
- **입력**: `resolved_query` + `candidates` + 대화 히스토리
- **처리**:
  - intent가 `chitchat`이면 `CHITCHAT` 프롬프트로 친근한 1~2문장 응답 (출처 없음)
  - candidates 비었거나 `sufficient=False`(retry 소진)면 *"해당 정보를 찾을 수 없습니다."* 즉시 반환 (도메인 grounded-only 정책, 6차)
  - 그 외에는 `GENERATE` 프롬프트로 문서 내용만 근거로 답변 생성, 본문에 `[1]`, `[2]` 인용 번호만 삽입
- **출처 정책 (인라인 링크 방식, 토큰 절감)**: 답변 본문 하단의 `**출처**` 블록 자체를 폐기. LLM은 본문에 `[N]`만 삽입하고, 서버는 LLM 스트림이 끝난 뒤 한 줄짜리 hidden 마커 `<!--CITES:[{"n":N,"url":"..."}]-->` 를 append. 프론트엔드(`web.py`의 `parseCites` + `renderText`)가 이 마커를 잘라내고 본문의 `[N]` 토큰을 해당 url로 가는 `<a class="cite">[N]</a>` 앵커로 자동 변환. 토큰 낭비 제거(긴 url·title 텍스트 미전송)와 디버깅 편의(어떤 [N]이 실제 인용되었는지 가시) 두 마리 토끼. LLM이 지시를 어기고 본문에 `**출처**`를 출력하면 `chat.py`의 `SOURCE_MARKER` sanitizer가 그 시점에 스트림을 truncate (멀티 chunk 분할 도착 안전 처리)
- **출력**: 최종 답변 (스트리밍)
- **UI 표시**: 4차에서 `✍️ 답변 생성 중...` 진행 메시지 제거. 직전 노드(`self_check`) 메시지 후 바로 구분선 → 답변 본문 토큰 스트리밍

#### [12] debug_explain (9차 신규, debugging intent 전용)
- **언제 호출되나?**: `query_analyze`가 intent를 `debugging`으로 분류한 경우. 검색 파이프라인은 완전히 우회
- **입력**: `user_id` + `current_query` (또는 `resolved_query`)
- **처리**:
  1. `user_id`가 비어 있으면 안내 메시지 후 종료 (per-user 인덱스가 없으면 디버그 불가)
  2. `fetch_recent_turns(user_id, n=3)`로 최근 3턴을 시간 역순으로 가져옴 (Turn 1 = 가장 최근)
  3. 0턴이면 "최근 대화 기록이 없어 디버깅할 수 없습니다" 안내 후 종료
  4. `_render_turns()`로 각 턴의 trace 필드(intent, search_intent, sub_queries, target_indices, search_plans, sufficient, sources, progress_log, final_answer)를 numbered block으로 렌더링
  5. `DEBUG_EXPLAIN` 프롬프트로 generator LLM에 전달 → LLM이 사용자 질의가 어느 턴을 가리키는지 판단해 한국어로 설명
- **LLM 판단 가이드 (`DEBUG_EXPLAIN` 프롬프트)**: 주제 참조("Kafka 답변") / 위치 참조("방금", "두 번째") / 일반 질의("왜 이렇게 답했어") → Turn 1 기본
- **출력**: `final_answer` (스트리밍, `on_chat_model_stream`이 chat.py SSE에 흘림), `sources=[]`
- **UI 표시**: `🐛 디버깅 모드: 최근 N턴 분석 완료`
- **로그 저장 정책**: debugging intent의 응답 자체는 `{user_id}_logs`에 저장하지 않음 (재귀적 자기 반영 방지)

#### [11] general_chat (3차 신규, 6차에서 진입 경로 축소)
- **언제 호출되나?**:
  1. `query_analyze`가 intent를 `general`로 분류한 경우 (도메인 외 질문 직행) — **유일한 진입 경로 (6차)**
  2. ~~검색 사이클(`hybrid_retrieve ↔ self_check`)이 retry 한도 도달 후 충분한 근거를 못 찾은 경우 (graceful fallback)~~ — 6차에서 제거. 도메인 질문이 ES에 답이 없으면 `generate`가 *"해당 정보를 찾을 수 없습니다"*로 응답. 일반 LLM 지식 폴백 금지
- **입력**: `resolved_query` + 대화 히스토리 (RAG 컨텍스트 없음)
- **처리**: `GENERAL_CHAT` 프롬프트로 일반 LLM 지식 답변 생성. 첫 줄에 `ℹ️ 사내 문서 범위 밖의 질문이라 일반 지식으로 답변드릴게요.` 안내 후 본 답변. 출처 섹션 없음
- **출력**: `final_answer` (스트리밍), `sources=[]`
- **UI 표시**: 4차에서 `💡 일반 대화로 답변 중...` 진행 메시지 제거. 직전 노드 메시지 후 바로 구분선 → 답변 본문 토큰 스트리밍

### 4.3 State 정의 (8차에서 `search_plans` 도입)

```python
class SearchPlan(TypedDict, total=False):
    """Per-(sub_query, index) 검색 계획 (8차 신규).
    인덱스별 언어 정책 차이로 한 sub-query를 N개 인덱스에 라우팅하면 N개 plan으로 fan-out."""
    sub_query_idx: int    # sub_queries[i] 참조
    sub_query: str        # 원문 sub-query (rewrite 전)
    index: str            # 라우팅된 인덱스명 (elasticsearch_docs / kafka_docs / confluence_docs)
    bm25: str             # 인덱스 언어 정책 적용 (ES/Kafka는 영어, confluence는 한국어)
    semantic: str         # 동일 정책

class RAGState(TypedDict):
    # 입력
    messages: list[Message]                       # 멀티턴 대화 히스토리
    current_query: str

    # 중간 산출물
    resolved_query: str          # 7차: query_reform이 생성 (search 분기일 때만). chitchat/general 경로에서는 미설정 → 다운스트림이 current_query로 폴백
    intent: Literal["question", "chitchat", "general", "debugging"]   # 7차: followup 제거 / 9차: debugging 추가
    search_intent: Literal["lookup", "count", "list"]   # 6차: ES 질의 형태
    user_id: str                                                       # 9차: 로그 저장 + debug 컨텍스트 조회용
    sub_queries: list[str]
    target_indices_per_query: list[list[str]]    # sub-query별 인덱스 목록 (index_route 산출, rewrite 입력)
    search_plans: list[SearchPlan]               # 8차: (sub-query × routed-index) 평탄화. rewrite 산출, retrieve/variate 입력
    metadata_filters: dict[str, Any]

    # 검색 결과
    candidates: list[Document]

    # 제어 플래그
    retry_count: int
    sufficient: bool

    # 출력
    final_answer: str
    sources: list[dict[str, str]]                # [{url, title}, ...]
```

> 8차에서 `rewritten_queries` / `semantic_queries` 1차원 배열은 폐기되고 `search_plans`로 통합. 리랭커 보류로 `reranked_docs` 필드는 제외.

---

## 5. 단계별 UI 표시 전략 (선택: A)

### 5.1 방식
각 LangGraph 노드 진입/종료 시 진행 상황 메시지를 답변 본문 앞에 SSE chunk로 스트리밍.
`generate` 노드의 LLM 토큰 스트리밍은 `astream_events(version="v2")`로 진행 메시지와 인터리브.

### 5.2 출력 포맷 예시

```
🔍 질문 분석 중... (intent=question)
🧩 질의 분해 중... (2개 서브쿼리)
   ├─ Elasticsearch RRF 동작 원리
   └─ RRF와 다른 하이브리드 방식 비교
✏️ 검색 쿼리 최적화 중...
   ├─ ES RRF 어떻게?
   │     • BM25:     Elasticsearch RRF reciprocal rank fusion
   │     • semantic: definition and mechanism of Reciprocal Rank Fusion in Elasticsearch
   └─ RRF 비교
         • BM25:     RRF hybrid fusion comparison
         • semantic: comparison between RRF and other hybrid retrieval fusion methods
🏷️  메타데이터 필터 추출 중...
🧭 인덱스 라우팅: elasticsearch
📚 Knowledge Base 검색 중.. (38건 발견)
  • Reciprocal Rank Fusion | Elasticsearch Guide
  • Hybrid search with RRF | Elasticsearch Guide
  • BM25 similarity | Elasticsearch Guide
🔎 검색 결과 검증 중... ✓ 충분
  ✓ Reciprocal Rank Fusion | Elasticsearch Guide
  ✓ Hybrid search with RRF | Elasticsearch Guide
  ✗ BM25 similarity | Elasticsearch Guide

─────────────────────────────────────

RRF(Reciprocal Rank Fusion)는 ... [1].
BM25와 semantic 검색의 순위를 결합하여 ... [2].
<!--CITES:[{"n":1,"url":"https://www.elastic.co/guide/..."},{"n":2,"url":"https://<your-internal-wiki>/..."}]-->
```

(클라이언트는 `<!--CITES:...-->` 마커를 본문에서 떼어내 표시하지 않고, 본문의 `[1]`·`[2]`만 해당 url로 가는 클릭 가능한 앵커로 변환)

> 분해/재작성 결과는 진행 메시지 안에 트리(`├─`/`└─`)로 동봉되어 클라가 단일 SSE chunk만 받아도 표시 가능. 별도 metadata 채널 불필요.
> CITES 마커는 url이 있는 항목만 포함 (빈 url 항목은 자동 스킵). 마커가 누락되면 `[N]`은 그냥 텍스트로 남고 답변 동작에는 영향 없음.

### 5.3 구현 노트
- 진행 메시지는 SSE chunk로 즉시 emit, 답변 토큰은 `on_chat_model_stream` 이벤트로 인터리브 (`generate` / `general_chat` 두 노드 모두 토큰 스트리밍 대상)
- 4차에서 `generate` / `general_chat` 노드 자체 진행 메시지(`✍️ 답변 생성 중...`, `💡 일반 대화로 답변 중...`)는 빈 문자열로 변경 → 답변 직전 노이즈 제거. 구분선은 첫 토큰 직전에 emit (`answer_emitted` 플래그)
- 내장 UI는 incremental append 방식이지만 구분선 위/아래를 회색 진행 박스 / 일반 본문(답변)으로 분리해 표시
- 외부 chatbot-ui 등을 붙일 경우 동일 SSE 포맷으로 동작 (시각 분리는 클라이언트 구현에 따름)

### 5.4 UI 테마 (iPhone / iMessage 라이트)
3차 변경에서 다크 GitHub 톤 → **iOS 라이트 테마 고정**으로 전환. 시스템 다크모드는 무시.

| 요소 | 디자인 |
|------|--------|
| 폰트 | SF Pro Text (`-apple-system`) + 한글 fallback (`Apple SD Gothic Neo`, `Noto Sans KR`), letter-spacing 살짝 negative |
| 컬러 | iOS 시스템 — systemBlue `#007AFF`, systemRed `#FF3B30`, systemGray `#E9E9EB`, systemGroupedBackground `#F2F2F7` |
| 네비게이션 바 | 반투명 + `backdrop-filter: blur(20px)` 글래스모피즘, 0.5px hairline separator, sticky top |
| 메시지 버블 | 18px round corner. user는 파란 그라디언트(`#2af → #007aff`) + 우하단 4px tail. assistant는 회색 + 좌하단 4px tail (iMessage 시그니처) |
| 진행 메시지 | 어시스턴트 회색 변형 + 모노스페이스 작은 글씨 |
| 입력창 | 둥근 직사각형(`border-radius: 22px`) 안에 textarea + 원형 ↑ 송신 버튼(34px, scale-on-press) |
| 로그인 카드 | iOS 모달 — 18px round, soft shadow, 풀와이드 입력/버튼 |
| 사용자 칩 | iOS pill (systemGray fill), 헤더 우측 |
| safe-area | 입력 영역 padding에 `env(safe-area-inset-bottom)` 반영 (홈 인디케이터 회피) |
| 모바일 | ≤520px에서 헤더 meta 숨김, 입력 키 width 축소 |

### 5.5 로그인 인트로 메시지 (3차 추가, 5차 타이핑 애니메이션)
로그인 직후 빈 채팅창에 **transient 어시스턴트 버블**로 인트로 메시지를 표시:

> 안녕하세요 저는 사내 문서 챗봇입니다. 무엇을 도와드릴까요?

- `messages` 배열에 push되지 않음 → 백엔드로 전송되는 history에 포함 X (대화 컨텍스트 오염 방지)
- **5차: 타이프라이터 스트림** — `setTimeout` 체인으로 글자당 35ms 간격 append. 250ms 초기 지연 후 시작. 자연스러운 등장감
- **취소 가능**: `introTimer` 핸들 + `introWrap` DOM 참조로 추적. 사용자가 스트림 도중 메시지를 보내거나 "대화 초기화"를 누르면 `cancelIntroStream()`이 즉시 타이머 해제 → detached 노드에 텍스트 append 방지
- 사용자가 첫 질문을 보내면 자동 제거 (`chat.innerHTML = ''`). 대화 영역 위에 인트로가 쌓이지 않음. "대화 초기화"를 누르면 다시 스트림

---

## 6. LLM 설정

### 6.1 연결 정보 (provider 스위치)

`app/services/llm_factory.py`가 `LLM_PROVIDER` 값에 따라 분기:

```python
# (a) openai — 현재 테스트
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(
    api_key=resolve_api_key(),       # Bearer 헤더 > .env OPENAI_API_KEY
    model=settings.openai_model,     # 기본 gpt-4o-mini
    base_url=settings.openai_base_url or None,  # OpenAI 호환 프록시 사용 시
    streaming=True,
)

# (b) azure — 사내 게이트웨이 운영
from langchain_openai import AzureChatOpenAI
llm = AzureChatOpenAI(
    azure_endpoint="https://<your-internal-gateway>/<path>/api/v3",
    azure_deployment="gpt-5.4-mini",
    api_version="2024-02-01",
    api_key=resolve_api_key(),       # Bearer 헤더 > .env HCHAT_API_KEY
    streaming=True,
)
```

> `resolve_api_key()`는 `ContextVar`에 담긴 per-request 헤더 값(`Authorization: Bearer <key>`)을 우선 반환하고, 없으면 provider별 `.env` 키로 폴백. `dummy`, `dummy-key`, `placeholder` 같은 placeholder 값은 헤더 추출 단계에서 필터링되어 폴백된다.

### 6.2 노드별 LLM 용도

| 노드 | 용도 | 스트리밍 | 온도 |
|------|------|---------|------|
| query_analyze | 3-intent 분류만 (7차에서 단순화, followup 제거) | ✗ | 0.0 |
| query_reform | history-aware self-contained 재작성 (7차 신규, history 없으면 LLM 스킵) | ✗ | 0.0 |
| search_intent | lookup/count/list 분류 (6차 신규) | ✗ | 0.0 |
| query_decompose | 서브쿼리 생성 | ✗ | 0.0 |
| query_rewrite | BM25 키워드 + semantic 명사구 (이중 출력) | ✗ | 0.0 |
| query_variate | retry 시 쿼리 다른 각도로 재작성 (6차 신규) | ✗ | 0.0 |
| metadata_extract | 필터 조건 추출 (JSON) | ✗ | 0.0 |
| index_route | 인덱스 결정 (JSON) | ✗ | 0.0 |
| self_check | 충분성 판단 | ✗ | 0.0 |
| es_count | LLM 호출 없음 (ES `_count`만, 6차 신규) | ✗ | — |
| es_list | LLM 호출 없음 (ES `terms` agg만, 6차 신규) | ✗ | — |
| **generate** | **RAG-grounded 답변 생성 / chitchat 응답** | **✓** | **0.3** |
| **general_chat** | **도메인 외 일반 질문 답변 (general intent 직행만)** | **✓** | **0.3** |

> 리랭커 보류 → `llm_rerank` 행 제거.

### 6.3 임베딩
- 쿼리/문서 임베딩 모두 ES `semantic_text` 필드가 자동 처리 (`text-embedding-3-small`, 1536d, cosine)
- 백엔드 코드는 `semantic` retriever 한 줄로 호출:
  ```json
  {"semantic": {"field": "content_semantic", "query": "<reformed query>"}}
  ```
- 별도 inference endpoint 호출이나 `query_vector_builder` 불필요

---

## 7. 세션/대화 관리

### 7.1 범위
- **세션 내 대화만** 기억 (장기 메모리 없음)
- 세션 = 단일 브라우저 탭의 대화 스레드 + URL의 `user_id` 파라미터

### 7.2 로그인 게이트 (URL 파라미터 기반)
- `GET /` 접근 시 URL에 `?user_id=<id>`가 없으면 **로그인 카드** 표시 (아이디 입력란 + 로그인 버튼)
- 로그인 폼 제출 → `/?user_id=<id>`로 리다이렉트, 챗봇 UI 노출
- 헤더 우측에 `👤 <id>` 칩 + 로그아웃 버튼 (로그아웃 시 `user_id` 파라미터 제거 → 다시 로그인 화면)
- 아이디 검증: `^[A-Za-z0-9._-]{1,64}$` (URL 안전 + injection 방지)
- 마지막 로그인 아이디는 `localStorage['rag-chat:lastUserId']`에 캐시 → 재방문 시 폼에 자동 채움
- 사용자 인증/권한 검증 아님 (단순 식별자). 실제 인증이 필요하면 사내 SSO 등을 별도 도입해야 함

### 7.3 저장 위치 (per-user 분리)
- 내장 UI는 브라우저 **localStorage**에 저장. user_id별로 키를 분리해 충돌 방지:
  ```
  STORAGE_KEY = 'rag-chat:messages:v2:' + userId
  ```
- 4차에서 헤더의 LLM API Key 입력칸을 제거 → 내장 UI는 `Authorization: Bearer` 헤더를 더 이상 보내지 않음. 서버는 `.env`의 `OPENAI_API_KEY` / `HCHAT_API_KEY`를 사용 (외부 OpenAI-호환 클라이언트가 헤더로 키를 보내는 경로 자체는 유지)
- 서버 측 별도 저장소 없음
- 매 요청 시 클라이언트가 `messages` 배열 전체를 백엔드로 전송 (OpenAI API 표준 동작)

### 7.4 멀티턴 처리 (7차에서 책임 분리)
- **분류 단계 (`query_analyze`)**: history는 "현재 질문이 도메인 주제 후속인지" 판단용으로만 사용 (분류만, 쿼리 재작성 X)
- **재작성 단계 (`query_reform`, search 분기 전용)**: history-aware 단일 책임 노드. 지시어 치환 + 생략 보완 → `resolved_query` 생성. history 비어 있으면 LLM 호출 스킵
- 예: 직전 답변이 "Elasticsearch의 RRF"에 대한 것이고, 현재 질문이 "어떻게 설정해?"인 경우 → `query_analyze` 결과 `intent=question` → `query_reform`이 `resolved_query="Elasticsearch RRF 설정 방법"`으로 펼침
- **다운스트림 영향**: `query_decompose`/`query_rewrite`/`metadata_extract`/`self_check`/`generate`는 모두 `resolved_query` 한 필드만 보면 되므로 history 직접 주입 불필요. 멀티턴 의존성을 단일 노드(`query_reform`)에 격리

### 7.5 컨텍스트 윈도우 관리
- 최근 N턴(기본 5턴, `MAX_HISTORY_TURNS`)만 LLM에 전달
- 초과 시 오래된 메시지부터 drop

---

## 8. OpenAI 호환 API 스펙

### 8.1 엔드포인트

```
GET  /                      # 내장 채팅 UI (HTML)
GET  /info                  # 서비스 메타데이터 (JSON)
GET  /health                # ES 연결 + 인덱스 존재 + LLM 키 설정 진단
GET  /v1/models             # OpenAI 호환
POST /v1/chat/completions   # OpenAI 호환 SSE
```

### 8.2 요청 (클라이언트가 보내는 형식)

```json
{
  "model": "rag-chatbot",
  "messages": [
    {"role": "user", "content": "이전 질문"},
    {"role": "assistant", "content": "이전 답변"},
    {"role": "user", "content": "현재 질문"}
  ],
  "stream": true,
  "temperature": 0.3
}
```

헤더:
```
Authorization: Bearer <openai-or-hchat-key>   # 선택, 있으면 .env 키를 덮어씀
```

### 8.3 응답 (SSE 스트리밍)

```
data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"},"index":0}]}

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":"🔍 질문 분석 중...\n"},"index":0}]}

... (단계별 진행 상황 스트리밍)

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":"─────────────────────────────────────\n"},"index":0}]}

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":"RRF는"},"index":0}]}

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{"content":" 문서 순위를"},"index":0}]}

... (답변 토큰 스트리밍)

data: {"id":"...","object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop","index":0}]}

data: [DONE]
```

---

## 9. 프로젝트 구조

```
auto-ever/
├── SPEC.md                          # 본 문서
└── backend/
    ├── pyproject.toml               # uv 프로젝트 (Python 3.11)
    ├── README.md
    ├── .env.example
    ├── app/
    │   ├── main.py                  # FastAPI 엔트리포인트, /info, /health
    │   ├── config.py                # Settings (pydantic-settings)
    │   ├── api/
    │   │   ├── chat.py              # POST /v1/chat/completions (SSE)
    │   │   ├── models.py            # GET /v1/models
    │   │   └── web.py               # GET / 인라인 채팅 UI
    │   ├── graph/
    │   │   ├── state.py             # RAGState TypedDict
    │   │   ├── workflow.py          # LangGraph StateGraph 빌더 + 4-intent 분기 + 사이클
    │   │   └── nodes/
    │   │       ├── query_analyze.py     # 3-intent 분류만 (7차에서 단순화)
    │   │       ├── query_reform.py      # history-aware self-contained 재작성 (7차 신규)
    │   │       ├── search_intent.py     # lookup/count/list 분류 (6차 신규)
    │   │       ├── query_decompose.py
    │   │       ├── query_rewrite.py
    │   │       ├── query_variate.py     # retry 시 쿼리 재작성 (6차 신규)
    │   │       ├── metadata_extract.py
    │   │       ├── index_route.py       # per-sub-query 인덱스 라우팅
    │   │       ├── hybrid_retrieve.py
    │   │       ├── self_check.py        # 6차: retry 한도 도달 시 generate로 폴백
    │   │       ├── es_count.py          # count 검색 의도 전용 (6차 신규)
    │   │       ├── es_list.py           # list 검색 의도 전용 (6차 신규)
    │   │       ├── generate.py          # RAG-grounded / chitchat 응답
    │   │       ├── general_chat.py      # 도메인 외 일반 답변 (3차 신규)
    │   │       └── debug_explain.py     # 9차 신규: {user_id}_logs 기반 trace 설명
    │   └── services/
    │       ├── elasticsearch_client.py  # build_rrf_query, hybrid_search
    │       ├── llm_factory.py           # provider switch + ContextVar
    │       └── log_store.py             # 9차 신규: per-user {user_id}_logs ES 인덱스
    └── tests/
        ├── test_es_query.py
        ├── test_helpers.py
        ├── test_nodes.py
        ├── test_workflow.py
        ├── test_api.py
        └── test_llm_factory.py
```

> 프롬프트는 별도 `.txt` 파일이 아니라 각 노드 모듈 내 인라인 (필요 시 `prompts/`로 분리 가능).
> Dockerfile / docker-compose.yml은 운영 전환 시 추가 예정.

---

## 10. 환경 변수

```bash
# Provider 스위치 ([필수])
LLM_PROVIDER=openai       # openai | azure

# OpenAI (LLM_PROVIDER=openai 일 때 [필수])
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini  # 선택, 기본 gpt-4o-mini
OPENAI_BASE_URL=          # 선택, OpenAI 호환 프록시 사용 시

# Azure / 사내 게이트웨이 (LLM_PROVIDER=azure 일 때 [필수])
HCHAT_API_KEY=<관리자-발급-키>
HCHAT_ENDPOINT=https://<your-internal-gateway>/<path>/api/v3
HCHAT_DEPLOYMENT=gpt-5.4-mini
HCHAT_API_VERSION=2024-02-01

# Elasticsearch ([필수])
ES_HOSTS=https://<es-host>:9200       # 콤마 구분 멀티노드 가능
ES_USERNAME=<user>
ES_PASSWORD=<password>
ES_INDEX_ELASTICSEARCH=elasticsearch_docs
ES_INDEX_KAFKA=kafka_docs
ES_INDEX_CONFLUENCE=confluence_docs    # 8차 신규 — 사내 Confluence 위키 (한국어 코퍼스)
ES_FIELD_TITLE=                        # 비워두면 BM25는 content 단일 필드 (현재 매핑에 title 없음)
ES_FIELD_CONTENT=content
ES_FIELD_SEMANTIC=content_embedding    # 실제 매핑의 semantic_text 필드명
ES_FIELD_URL=url                       # 인덱스에 채워지면 출처 섹션에 자동 표시
ES_VERIFY_CERTS=false                  # 폐쇄망 자체 인증서 환경 기본값
ES_CA_CERTS=                           # 사내 CA 번들 경로 (있을 때)

# Retrieval
RETRIEVAL_RANK_WINDOW=50
RETRIEVAL_RANK_CONSTANT=60
RETRIEVAL_TOP_K=10
RETRIEVAL_MAX_RETRY=2

# Conversation
MAX_HISTORY_TURNS=5

# Server
BACKEND_PORT=8000
LOG_LEVEL=INFO
```

> Per-request 키: 클라이언트가 `Authorization: Bearer <key>` 헤더로 보내면 위 `OPENAI_API_KEY` / `HCHAT_API_KEY`를 덮어쓴다. 헤더 값이 `dummy`, `dummy-key`, `placeholder` 같은 폼이면 무시되고 `.env` 폴백.

---

## 11. 프롬프트 정책

### 11.1 공통 원칙
- 챗봇 표시 명칭은 **"사내 문서 챗봇"(`CHATBOT_NAME` 설정값)** (UI / `CHITCHAT` / `GENERAL_CHAT` 프롬프트 모두 동일)
- **8차 기준 모든 프롬프트의 prose는 영어** — LLM이 영어 instruction을 더 안정적으로 따른다는 사용자 판단. 다만:
  - 예시(few-shot) 섹션의 입력 쿼리는 **한국어 그대로 유지** (실제 사용자 입력 분포에 맞춤)
  - 챗봇 출력에 등장하는 한국어 리터럴은 보존 (`"해당 정보를 찾을 수 없습니다."`, `"사내 문서 챗봇"(`CHATBOT_NAME` 설정값)` 정체성 문구, `"ℹ️ 사내 문서 범위 밖의 질문이라 일반 지식으로 답변드릴게요."` 등)
  - `GENERATE` / `CHITCHAT` / `GENERAL_CHAT`은 첫 줄에 `Respond in Korean.` 명시
  - `QUERY_REFORM`은 출력이 한국어 self-contained 문장이므로 "Output in Korean" 명시
- **인덱스별 언어 정책 (8차)**: `QUERY_REWRITE` / `QUERY_VARIATE`는 `{target_index}` 플레이스홀더를 받아 분기. ES/Kafka 인덱스는 영어 출력, Confluence는 한국어 출력 (기술용어는 영어 유지)
- LLM 판단 노드(`metadata_extract`, `index_route`, `self_check`, `query_decompose`, `query_rewrite`, `query_analyze`, `query_reform`, `query_variate`, `search_intent` 등)는 **JSON 출력 강제**
- `generate`(RAG): `검색 결과에 없으면 "해당 정보를 찾을 수 없습니다"로 답변` 명시
- `CHITCHAT`: 매번 역할 안내 반복 금지. 친근한 1~2문장. 정체성 질문에만 짧은 소개
- `GENERAL_CHAT`: 첫 줄에 *"ℹ️ 사내 문서 범위 밖의 질문이라 일반 지식으로 답변드릴게요."* 안내 + 본 답변. 출처 섹션 만들지 않음

### 11.3 프롬프트 인벤토리 (8차 기준)
- `QUERY_ANALYZE` — 4-intent 분류 (7차: followup 제거 / 8차: 도메인 카테고리 3개로 확장 + Internal-wiki(Confluence) 키워드 17종 추가 / 9차: `debugging` intent 추가). 도메인 단어 절대 규칙 + 비교 질문 처리 유지. debugging vs question 구분 규칙 명시 ("X가 뭐야?" → question, "왜 X 답변이 그래?" → debugging)
- `DEBUG_EXPLAIN` (9차 신규) — `{user_id}_logs`의 최근 3턴 trace를 받아 사용자가 가리키는 턴을 LLM이 판단하고 한국어로 설명. 주제·위치·일반 참조 모두 처리. `[Turn N]` 형태로 인용
- `QUERY_REFORM` — history-aware self-contained 재작성 (7차 신규). 지시어 치환 + 생략 보완. 한국어 유지(번역 X). 4개 예시
- `SEARCH_INTENT_CLASSIFY` — 검색 형태 분류 lookup/count/list (6차 신규)
- `QUERY_DECOMPOSE` — 서브쿼리 분해 (영문 + JSON, 한국어 도메인 예시 다수)
- `QUERY_REWRITE` — 서브쿼리 → BM25 + semantic (이중 출력, HyDE 금지). **8차: `{target_index}` 플레이스홀더 + 인덱스별 언어 정책 (ES/Kafka 영어, Confluence 한국어). few-shot 9개 (영어 6개 + Confluence 한국어 3개)**
- `QUERY_VARIATE` — retry 사이클에서 쿼리를 다른 각도로 재작성 (BROADEN/SYNONYMS/DIFFERENT ANGLE/ADD DOMAIN/DECOMPOSE FURTHER 5전략, 6차 신규). **8차: `{target_index}` 플레이스홀더 + 변형 후에도 같은 인덱스 언어 정책 유지**
- `METADATA_EXTRACT` — 필터 추출 (보수적). 8차: `source` 예시를 `["elasticsearch","kafka","confluence"]`로 갱신
- `INDEX_ROUTE` — 인덱스 라우팅 (per-sub-query). **8차: `"confluence"` 옵션 추가, 사내 운영 맥락 + 공개 기술 토픽 동시 등장 시 양쪽 인덱스 라우팅 가이드 명시**
- `SELF_CHECK` — 충분성 판단
- `GENERATE` — RAG-grounded 답변 (6차: `**출처**` 섹션 LLM 작성 금지). 8차: 본문 영어화, 한국어 응답 명시
- `CHITCHAT` — 인사·정체성 응답. 8차: 정체성 문구 `"Elasticsearch / Kafka 공식문서 + Confluence 사내 위키"`로 갱신
- `GENERAL_CHAT` — 도메인 외 일반 답변 (3차 신규, 6차에서 진입 경로 축소). 8차: 도메인 범위 안내에 Confluence 추가

### 11.2 Generate 프롬프트 핵심 지침
```
- 아래 제공된 문서의 내용만 근거로 답변하세요.
- 문서에 없는 내용은 절대 생성하지 마세요.
- 답변 본문에 [1], [2] 형태로 인용을 삽입하세요.
- 인용 번호는 제공된 문서 순서와 일치해야 합니다.
- 답변 마지막에 "**출처**" 섹션을 만들고 각 인용 번호에 해당하는 url을 나열하세요.
- 검색 결과가 질문과 무관하면 "해당 정보를 찾을 수 없습니다"로 답변하세요.
```

---

## 12. 배포

### 12.1 현재 (개발/테스트)

uv 단독 실행. Docker / docker-compose는 사용하지 않음:

```bash
cd backend
uv sync --all-extras
cp .env.example .env && $EDITOR .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://<host>:8000/`로 접속하면 내장 채팅 UI가 뜬다.

테스트:
```bash
uv run pytest -q
```

진단:
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
# elasticsearch.reachable: true, indices.*: true, llm.api_key_configured: true 면 정상
```

### 12.2 추후 운영 (사내 폐쇄망 전환 시)

- `LLM_PROVIDER=azure` + `HCHAT_API_KEY` 세팅
- 필요 시 Docker / docker-compose 추가 (현재 미작성)
- 사내 CA 인증서: `ES_CA_CERTS=/path/to/ca.pem` + `ES_VERIFY_CERTS=true`
- 사내 게이트웨이, Elasticsearch로의 네트워크 경로 방화벽 오픈 확인

---

## 13. 범위 외 (Out of Scope)

- 문서 인덱싱 파이프라인 (기존 인프라 활용)
- 문서 청킹/임베딩 (이미 완료됨, `semantic_text`가 처리)
- 인증/권한 관리 (per-request Bearer 키는 LLM 호출용일 뿐 사용자 인증 아님)
- 관측/평가 (LangSmith, RAGAS 등)
- 장기 메모리 시스템
- 멀티 사용자 동시성 고려 (단일 VM 단독 운영)
- 리랭커(ES `text_similarity_reranker` / LLM 리랭크) — M10 이전 보류
- Docker / docker-compose 패키징 — M11 이전 보류

---

## 14. 마일스톤

| 단계 | 내용 | 상태 |
|------|------|------|
| M1 | FastAPI OpenAI 호환 서버 + 내장 채팅 UI (`GET /`) | ✅ 완료 |
| M2 | Elasticsearch 하이브리드 검색 (`retriever.rrf`) 모듈 | ✅ 완료 |
| M3 | LangGraph 기본 플로우 (analyze → decompose → rewrite → metadata → route → retrieve → generate) | ✅ 완료 |
| M4 | self_check + 재시도 루프 (리랭커는 보류) | ✅ 완료 |
| M5 | 단계별 UI 스트리밍 (`astream_events` v2로 진행/토큰 인터리브) | ✅ 완료 |
| M6 | 멀티턴 처리 (query_analyze에서 resolved_query 생성) | ✅ 완료 |
| M7 | per-sub-query 인덱스 라우팅 (`elasticsearch_docs` / `kafka_docs`) | ✅ 완료 |
| M8 | LLM provider 스위치 (OpenAI 테스트용 / Azure 운영) + Bearer 헤더 키 오버라이드 | ✅ 완료 |
| M9 | 실데이터 적합화 — BM25 단일 필드 fallback, metadata_extract 보수화, 출처 url 안전장치, 매핑 진단 | ✅ 완료 |
| M10 | UI UX — 분해/재작성 결과 트리 표시, `query_decompose` 영문 프롬프트 + JSON 강제, 로그인 게이트(`?user_id=<id>`) + per-user 대화 분리 | ✅ 완료 |
| M11 | 브랜딩 + 4-intent 라우팅 — "사내 문서 챗봇"(`CHATBOT_NAME` 설정값)으로 통일, `general` intent 추가, `general_chat` 노드 신규, 사이클 fallback (`hybrid_retrieve ↔ self_check → general_chat`), `CHITCHAT` 프롬프트 친근화, 로그인 인트로 메시지 | ✅ 완료 |
| M12 | UI 테마 iOS/iMessage 라이트로 전환 (다크모드 무시), backdrop blur 네비, 그라디언트 버블, 원형 ↑ 송신 버튼, safe-area 지원, 모바일 반응형 | ✅ 완료 |
| M13 | 이중 쿼리 재작성 + UI 최소화 — `QUERY_REWRITE` 영어 `keywords`/`semantic` 2-output (semantic은 명사구 4~12 토큰, HyDE 금지), `semantic_queries` state 필드, `build_rrf_query` BM25/semantic 별도 텍스트, `QUERY_DECOMPOSE` 한국어 도메인 예시 추가, 헤더 API key/meta 표시 제거, `generate`/`general_chat` 진행 메시지 제거 | ✅ 완료 |
| M14 | 인트로 메시지 타이핑 애니메이션 — 35ms/char 스트림, 250ms 초기 지연, 안전한 취소 로직 (`introTimer` + `cancelIntroStream()`). 5.1차에서 첫 메시지 후에도 영구 표시로 전환 | ✅ 완료 |
| M15 | 검색 의도 분기 + 도메인 grounding 강화 — `search_intent`(lookup/count/list) 노드, `query_variate` retry 변형, `query_analyze` 도메인 단어 정규식 안전망, retry 소진 시 `general_chat` 폴백 제거(grounded-only), 출처 중복 픽스, `general` whitelist 픽스 | ✅ 완료 |
| M16 | intent 분류 ↔ 쿼리 재작성 분리 — `query_analyze`를 3-intent 분류만 담당하도록 단순화(`followup` 제거), `query_reform` 노드 신규로 history-aware self-contained 재작성을 단일 책임으로 추출, history 빈 경우 LLM 호출 스킵, `list_titles` 집계 필드를 `title.keyword`로 교체 | ✅ 완료 |
| M17 | 사내 Azure 게이트웨이 전환 + 실제 ES 인덱스 보강(title/url/source/category/updated_at) | ⏳ 대기 |
| M18 | 리랭커 (필요 시) — ES `text_similarity_reranker` 또는 LLM 리랭크 | ⏳ 보류 |
| M19 | Docker / docker-compose 패키징 (운영 전환 시) | ⏳ 보류 |
| M20 | 프롬프트 튜닝 + 출처 포맷 확정 | ⏳ 진행 중 |
