# 운영가이드 (OPERATIONS)

이 문서는 RAG 챗봇 백엔드의 **인덱스 추가**와 **검색 쿼리 수정** 절차를
정리합니다. 모든 파일 경로는 저장소 루트 기준입니다.

현재 운영 중인 인덱스 (`elasticsearch_docs`, `kafka_docs`, `confluence_docs`,
`chat_logs`, `chat_md`) 와 관련 흐름은 [SPEC.md](../SPEC.md) 참조.

---

## 1. 새 검색 인덱스 추가

새 검색 코퍼스(예: `jira_docs`, `runbook_docs`)를 라우팅·재검색·쿼리 재작성
대상에 포함시키는 절차입니다. 채팅 로그 같은 시스템 인덱스 추가는 별개
작업(이 문서 범위 밖).

### Step 1 — ES 측 인덱스 생성

다음 필드 매핑은 검색 코드가 가정하는 최소 스키마입니다.

| 필드 | 타입 | 비고 |
|---|---|---|
| `title` | `text` (+ `keyword` subfield) | `list_titles()` 집계용 `.keyword` 필요 |
| `content` | `text` | BM25 본문 |
| `content_embedding` | `semantic_text` | ES 8.14+ semantic 필드. text-embedding-3-small 매핑 |
| `url` | `keyword` | 출처 링크 |
| `source` / `category` | `keyword` | 메타데이터 필터용 |
| `updated_at` | `date` | 날짜 범위 필터용 |
| `ancestors.title` *(선택)* | `text` | confluence처럼 페이지 계층이 있을 때만 |

`backend/app/services/elasticsearch_client.py:32` 의 `build_rrf_query` 가
`ancestors.title` 을 `lenient: true` 로 검색하므로 이 필드가 없어도 쿼리는
실패하지 않습니다.

### Step 2 — 환경변수 등록

**`backend/.env.example`** 과 운영 환경의 **`backend/.env`** 양쪽에 추가:

```bash
ES_INDEX_RUNBOOK=runbook_docs
```

`.env.example` 의 인덱스 섹션 주석에도 새 코퍼스의 언어/성격을 한 줄로
적어두면 좋습니다 (영문 공식 docs인지 한국어 사내 코퍼스인지).

> **인덱스명 우선순위.** `.env` 의 값 → (없으면) `config.py` 의 default
> 값 순서로 적용됩니다. 즉 `.env` 에 `ES_INDEX_RUNBOOK` 을 빠뜨려도
> Step 3 에서 등록한 default(`"runbook_docs"`) 가 그대로 쓰여 코드는
> 동작합니다 — 하지만 운영 환경에서는 항상 `.env` 에 명시해 두는 것이
> 안전합니다 (default 변경 시 의도치 않은 인덱스로 트래픽이 흐르는
> 사고를 막기 위함).
>
> 현재 `backend/.env` 에는 `ES_INDEX_ELASTICSEARCH`,
> `ES_INDEX_KAFKA` 만 명시돼 있고 `ES_INDEX_CONFLUENCE` 는 config.py
> default(`"confluence_docs"`) 에 의존합니다. 새 인덱스를 추가할 때
> 이 관행을 따를지, `.env` 에 명시할지는 팀 정책에 맞추세요.

### Step 3 — `config.py` 등록

**`backend/app/config.py`**:

```python
# Settings 클래스
es_index_runbook: str = "runbook_docs"

# all_indices property — 메타 카운트/리스트 fallback에 쓰임
@property
def all_indices(self) -> list[str]:
    return [
        self.es_index_elasticsearch,
        self.es_index_kafka,
        self.es_index_confluence,
        self.es_index_runbook,           # ← 추가
    ]

# index_alias_map — LLM이 emit하는 canonical alias → 실제 인덱스명
@property
def index_alias_map(self) -> dict[str, str]:
    return {
        "elasticsearch": self.es_index_elasticsearch,
        "kafka":         self.es_index_kafka,
        "confluence":    self.es_index_confluence,
        "runbook":       self.es_index_runbook,   # ← 추가
    }
```

`index_alias_map` 의 key가 LLM이 `forced_indices` 와 `indices` 필드에
반드시 사용해야 하는 **canonical 이름**입니다. 이후 모든 프롬프트와
화이트리스트에서 이 정확한 문자열을 씁니다.

### Step 4 — 인덱스 라우팅 프롬프트 (`INDEX_ROUTE`)

**`backend/app/prompts.py:457`** `INDEX_ROUTE`:

1. `Available indices:` 섹션에 새 alias 항목을 추가하고 **언제 라우팅
   하는지/안 하는지** 를 적습니다. 단독 라우팅인지, confluence와 함께
   라우팅하는 운영 토픽이 있는지 등.
2. `Routing guidance:` 에 우선순위 규칙을 1~2줄 추가.
3. `라우팅 예시:` 섹션에 **단독 / 조합 / 사내 맥락** 케이스를 각 1개 이상.
4. JSON 스키마 코멘트가 alias 목록을 나열한다면 거기도 추가:
   ```
   {{"indices": ["elasticsearch", "kafka", "confluence", "runbook"]}}
   ```

라우팅 코드(`app/graph/nodes/index_route.py`)는 alias만 매칭해서
`alias_map[alias]` 로 실 인덱스명을 해석하므로 **코드 수정은 불필요**합니다.

### Step 5 — `query_analyze` 프롬프트 + 화이트리스트

**`backend/app/prompts.py:9`** `QUERY_ANALYZE`:

- `HARD RULES` 의 **도메인 단어 목록**에 새 코퍼스의 키워드를 추가
  (질문에 이 단어가 보이면 `question` 으로 강제하기 위함).
- `re_search` 섹션의 **canonical 이름 목록**과 예시에 `runbook` 추가:
  ```
  - "runbook" — for: runbook / 런북 / 운영 런북 / 사내 운영 런북 ...
  ```
- JSON 스키마의 `forced_indices` 허용 값 주석도 갱신.

**`backend/app/graph/nodes/query_analyze.py`** 의 화이트리스트:

```python
_VALID_FORCED_INDICES = frozenset({
    "elasticsearch", "kafka", "confluence", "runbook",   # ← 추가
})
```

이 화이트리스트는 LLM이 hallucinate한 alias를 걸러내는 1차 방어선입니다.
새 alias를 추가하지 않으면 LLM이 `"runbook"` 을 emit해도 빈 리스트가 되어
`re_search` 가 `question` 으로 fallback됩니다.

### Step 6 — `query_rewrite` 프롬프트 (언어 정책)

**`backend/app/prompts.py:341`** `QUERY_REWRITE` 는 인덱스마다 BM25/semantic
출력 언어를 다르게 지시합니다. 새 인덱스의 코퍼스 언어를 명시:

```
- target_index == "runbook_docs":
  Korean corpus (사내 운영 런북 — 한국어 작성, 기술용어만 영어). Output
  BOTH `keywords` and `semantic` in KOREAN, PRESERVE technical terms in
  English exactly as Korean engineers write them.
```

이미 영어 코퍼스용 / confluence-style 한국어 코퍼스용 정책이 정의돼 있으니
새 인덱스가 둘 중 한 패턴을 따른다면 해당 분기에 인덱스명을 끼워넣는 식이
가장 안전합니다. 또한 새 인덱스를 사용하는 **예시 한두 개** 를 12개 예시
블록 뒤에 추가하면 LLM 일관성이 더 좋아집니다.

### Step 7 — (선택) 사내 코퍼스라면 사내 고유명사 등록

새 인덱스가 사내 고유명사 / 사내 운영 컨텍스트 전용이라면
**`backend/app/internal_terms.json`** 에 관련 단어를 추가합니다. 이 파일은
`_INTERNAL_PATTERN`(`query_analyze.py`)과 `INDEX_ROUTE` 프롬프트 양쪽에
주입되고, `index_route._route_one()` 이 `_has_internal_term(query)` 로 검사해
**LLM 판정과 무관하게** confluence(또는 새 사내 인덱스)를 force-include
합니다.

```json
{
  "products":   ["제품명 — 부분 문자열로 매칭"],
  "acronyms":   ["약어 — ASCII 단어 경계로 매칭"],
  "locations":  ["사옥/지역"],
  "org":        ["조직/도메인"],
  "namespaces": ["/인덱스_경로_접두사"]
}
```

**이 파일은 저장소에 포함되지 않습니다.** 실제 사내 용어는 특정 회사를
지목하는 정보라서 `.gitignore` 대상이고, 추적되는 것은 플레이스홀더인
`internal_terms.example.json` 뿐입니다. 배포 환경마다 직접 만들어 두거나
`INTERNAL_TERMS_FILE` 로 경로를 지정하세요. 파일이 없으면 예시 파일로
폴백하며, 이때 사내 고유명사 기반 강제 라우팅은 사실상 동작하지 않습니다
(기동 로그에 warning이 남습니다).

"운영 중인", "장애 이력" 같은 **운영 상태 표현**은 어느 회사에서나 같은
뜻이므로 코드(`_INTERNAL_STATE_ALTERNATIVES`)에 그대로 남아 있습니다.

새 인덱스 자체에 대한 force-include 규칙이 필요하면 `_route_one` 의
confluence 강제 추가 로직(`index_route.py`) 을 참고해 같은 패턴으로
추가하면 됩니다.

### Step 8 — 검증 체크리스트

```bash
cd backend
uv run python -m pytest                         # 154+ 테스트 모두 통과
uv run python -c "from app.config import get_settings; s = get_settings(); \
  print(s.all_indices); print(s.index_alias_map)"
```

수동 검증:

| 시나리오 | 입력 | 기대 동작 |
|---|---|---|
| 라우팅 단독 | "런북에서 ES 배포 절차 알려줘" | `indices=["runbook"]` (LLM 판정) |
| 재검색 명시 | "런북에서 다시 찾아줘" | `intent=re_search`, `forced_indices=["runbook"]` |
| 도메인 강제 | "런북" 단독 메시지 | `intent=question` (chitchat/general로 빠지지 않음) |
| 쿼리 재작성 | confluence-style 한국어면 한국어 BM25, ES/Kafka-style 영어면 영어 BM25 | `query_rewrite.py` 결과 확인 |

체크리스트가 다 맞으면 인덱스 추가 완료.

---

## 2. 검색 쿼리 수정

"검색 쿼리"는 여러 레이어가 겹쳐 있어서 **무엇을** 바꾸려는지에 따라 손
대는 파일이 다릅니다. 아래 표는 의도 → 파일 매핑.

### 2.1 레이어 한눈에 보기

```
사용자 질문
   │
   ├─[query_reform]    후속 질문의 지시어("그것","이건") → 자립 질문으로 치환
   ├─[query_decompose] 복합 질문을 sub_queries 리스트로 분해
   ├─[index_route]     각 sub_query → 대상 인덱스 목록 (LLM 판정)
   ├─[query_rewrite]   (sub_query × index)마다 (BM25, semantic) 쌍 생성
   ├─[metadata_extract] 날짜·source·category 같은 구조화 필터 추출
   │
   ├─[hybrid_retrieve] search_plans를 ES에 전송 (top_k는 재시도 차수별)
   │     └─ hybrid_search() → ES RRF 쿼리 DSL 빌드 & 실행
   │
   ├─[self_check]      충분성 판단
   │   └─ 불충분 → [query_variate] BM25/semantic 문자열 재생성 → hybrid_retrieve 루프
   │
   └─[generate]        retrieved docs로 최종 답변 생성
```

### 2.2 수정 의도별 파일 매핑

#### "BM25 키워드/semantic 문장 만드는 방식을 바꾸고 싶다"

→ **`backend/app/prompts.py:341`** `QUERY_REWRITE`

손볼 만한 곳:

- **언어 정책** — 새 인덱스 추가하거나 한국어/영어 정책 바꿀 때.
- **stopword/조사 제거 룰** — "어떤 토큰을 버려야 하는가" 변경.
- **기술용어 normalization 사전** — `엘라스틱서치 → Elasticsearch` 같은 매핑.
- **semantic noun-phrase 템플릿** — "X 정의 / X 동작 원리" 같은 허용 형식.
- **FORBIDDEN 룰** — HyDE 스타일 가상 답변 금지 등.
- **날짜 토큰 보존 룰** — `2024-08-15` 같은 토큰을 BM25/semantic 양쪽에
  남길지.
- **synthesis 동사 금지 룰** — "비교/요약/정리" 같은 LLM 태스크는 검색어에서
  제거.
- **예시 추가** — 12개 worked example. 새 패턴 가르치고 싶을 때 케이스 추가.

코드 쪽 `backend/app/graph/nodes/query_rewrite.py` 는 LLM을 호출해서
`(keywords, semantic)` 을 받고 빈 응답에 대한 fallback만 처리하므로 보통
손댈 일이 없습니다.

#### "재검색 시 쿼리 변형 로직을 바꾸고 싶다"

→ **`backend/app/prompts.py:585`** `QUERY_VARIATE`

`self_check` 가 불충분이라고 판정한 뒤 `query_variate` 가 호출됩니다.
**다른 각도** 로 BM25/semantic 을 재생성하는 룰을 여기서 조정.

루프 동작 자체(몇 번 재시도, 재시도마다 top_k 얼마)는 **`.env`** 의
`RETRIEVAL_TOP_K_SCHEDULE=[10,20,30]` 배열로 조정. 배열 길이 = 최대 검색
시도 횟수. `backend/app/graph/nodes/hybrid_retrieve.py` 가 attempt index
로 이 배열을 인덱싱.

#### "메타데이터 필터(날짜·source·category)를 다르게 뽑고 싶다"

→ **`backend/app/prompts.py:435`** `METADATA_EXTRACT`

- 새 필터 필드 추가 시: 이 프롬프트의 JSON 스키마에 필드 추가, 그리고
  **`backend/app/services/elasticsearch_client.py:122`** `_build_filter_clauses`
  에도 필드 처리 분기 추가, 그리고 ES 인덱스 매핑에 keyword 필드 추가.
- 날짜 형식 인식 룰만 바꿀 거라면 프롬프트만 수정.

#### "실제 ES 쿼리 DSL을 바꾸고 싶다"

→ **`backend/app/services/elasticsearch_client.py`**

| 변경 의도 | 위치 |
|---|---|
| BM25 필드 부스트 (예: `title^2` → `title^3`) | `build_rrf_query()` `bm25_fields` 리스트 |
| RRF `rank_window_size` / `rank_constant` | `.env` `RETRIEVAL_RANK_WINDOW` / `RETRIEVAL_RANK_CONSTANT` |
| 기본 `size` (top_k) | `.env` `RETRIEVAL_TOP_K` (단발) 또는 `RETRIEVAL_TOP_K_SCHEDULE` (재시도 루프) |
| `_source` 반환 필드 | `build_rrf_query()` 의 `_source` 리스트 |
| RRF → 단일 retriever / 다른 fusion 방식 변경 | `build_rrf_query()` 의 `retriever` 트리 통째로 |
| highlighter / aggregations / explain 추가 | `build_rrf_query()` 반환 dict에 키 추가 |
| 진단용 BM25-only / semantic-only 비교 | `_build_single_retriever_query()` (chat_logs 진단 로그) |

`build_rrf_query` 는 ES 8.14+ `retriever DSL` 구조라 클러스터 버전 호환에
주의. 그 아래 버전이면 `search_after` + RRF 수동 fusion 으로 다시 짜야 합니다.

#### "질문 분해(sub_queries) 규칙을 바꾸고 싶다"

→ **`backend/app/prompts.py:254`** `QUERY_DECOMPOSE`

"ES와 Kafka 차이" 같은 cross-domain 질문이 어떻게 쪼개지는지 규칙.

#### "후속 질문 reformulation 을 바꾸고 싶다"

→ **`backend/app/prompts.py:123`** `QUERY_REFORM`

"그게 뭐야?" 의 "그게" 같은 지시어/대명사를 직전 턴 토픽으로 치환하는 룰.

#### "검색 의도 분류(lookup/count/list)를 바꾸고 싶다"

→ **`backend/app/prompts.py:539`** `SEARCH_INTENT_CLASSIFY`

`count` / `list` 분기로 가면 `hybrid_retrieve` 대신 `es_count` /
`es_list` 로 라우팅되므로, 분류 룰 변경이 워크플로우 분기에 직접 영향.

### 2.3 변경 후 검증

| 변경 범위 | 최소 검증 |
|---|---|
| 프롬프트만 수정 | `uv run python -m pytest`; 변경 영역과 무관한 회귀 테스트가 깨졌는지 확인 |
| `query_rewrite` 프롬프트 | 실제 질문 몇 개로 chat_logs 의 `search_plans` 출력 확인 |
| ES DSL (`elasticsearch_client.py`) | 인덱스/필드 의존성이 있으므로 실 ES 클러스터에 쿼리 보내서 응답 스키마 확인 |
| `RETRIEVAL_*` env | 백엔드 재시작 필요 (`Settings` 은 `@lru_cache`) |
| `INDEX_ROUTE` / `QUERY_ANALYZE` | 의도 다양한 질문 10여 개로 라우팅 결과 sanity check |

LangGraph 워크플로우 자체(`backend/app/graph/workflow.py`) 는 노드 추가/제거
정도가 아닌 이상 검색 쿼리 수정 만으로는 건드릴 일이 거의 없습니다.

---

## 부록 A — 자주 참조하는 파일

```
backend/
├── .env / .env.example          환경변수 (인덱스명, top_k 스케줄, ES/LLM 인증)
├── app/
│   ├── config.py                Settings, all_indices, index_alias_map
│   ├── prompts.py               모든 LLM 프롬프트 (QUERY_*, INDEX_ROUTE, ...)
│   ├── graph/
│   │   ├── workflow.py          LangGraph 노드 연결
│   │   ├── state.py             RAGState, SearchPlan 타입
│   │   └── nodes/
│   │       ├── query_analyze.py     intent 분류 + _VALID_FORCED_INDICES + 도메인 regex
│   │       ├── query_reform.py      후속 질문 자립화
│   │       ├── query_decompose.py   sub_queries 분해
│   │       ├── index_route.py       sub_query → 인덱스 매핑 (LLM + 사내 고유명사 force)
│   │       ├── query_rewrite.py     (sub_query × index) → (BM25, semantic)
│   │       ├── metadata_extract.py  날짜/source/category 필터 추출
│   │       ├── hybrid_retrieve.py   search_plans 실행, top_k 스케줄링
│   │       ├── self_check.py        충분성 판단, retry budget
│   │       ├── query_variate.py     재시도 시 쿼리 변형
│   │       ├── re_search_setup.py   강제 재검색 ("xxx에서 다시 찾아줘")
│   │       └── generate.py          최종 답변 생성
│   └── services/
│       ├── elasticsearch_client.py  hybrid_search, build_rrf_query, filter clauses
│       └── llm_factory.py            judge_llm / generator_llm 인스턴스
└── tests/                        pytest 회귀 테스트
```

## 부록 B — `.env` 주요 검색 파라미터

```bash
# 인덱스 (Step 2 참조)
# 현재 .env 에는 ELASTICSEARCH, KAFKA 만 명시. CONFLUENCE 는 config.py
# default("confluence_docs") 에 의존 — 필요 시 .env 에 명시 추가.
ES_INDEX_ELASTICSEARCH=elasticsearch_docs
ES_INDEX_KAFKA=kafka_docs
ES_INDEX_CONFLUENCE=confluence_docs   # 선택 — 미지정 시 config.py default

# 필드 (Step 1 매핑과 일치해야 함)
ES_FIELD_TITLE=title
ES_FIELD_CONTENT=content
ES_FIELD_SEMANTIC=content_embedding
ES_FIELD_URL=url

# 검색 파라미터
RETRIEVAL_RANK_WINDOW=100        # RRF가 fusion 전 후보로 보는 윈도우
RETRIEVAL_RANK_CONSTANT=60       # RRF k (1/(k+rank))
RETRIEVAL_TOP_K=20               # 기본 top_k (단발 검색에 쓰임)
RETRIEVAL_TOP_K_SCHEDULE=[10,20,30]  # 재검색 루프 배열. 길이 = 최대 시도

# LLM에 전달되는 문서 길이 제한
GENERATE_DOC_CHAR_LIMIT=5000
SELF_CHECK_DOC_CHAR_LIMIT=1000
```

값 변경 후에는 백엔드를 **재시작** 해야 `Settings` 가 다시 로드됩니다.

