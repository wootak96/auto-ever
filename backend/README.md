# RAG Chatbot Backend

OpenAI-compatible RAG server. FastAPI + LangGraph in front of Elasticsearch
(`elasticsearch_docs`, `kafka_docs`). Includes a built-in chat UI at `GET /`.

## Quick start

```bash
uv sync --all-extras
cp .env.example .env                                    # fill in [필수] sections
cp app/internal_terms.example.json app/internal_terms.json   # 사내 용어 (아래 참조)
$EDITOR .env app/internal_terms.json
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

브라우저로 `http://localhost:8000/` 접속하면 채팅 UI가 뜹니다.

## .env 채우기 가이드

`backend/.env`의 **[필수]** 항목만 채우면 동작합니다.

### 1) LLM 프로바이더 선택

| `LLM_PROVIDER` | 채워야 할 키 | 비고 |
|----------------|--------------|------|
| `openai` (테스트용) | `OPENAI_API_KEY` (선택: `OPENAI_MODEL`, `OPENAI_BASE_URL`) | 퍼블릭 OpenAI 또는 OpenAI 호환 프록시 |
| `azure` (운영) | `HCHAT_API_KEY` | 사내 게이트웨이. `HCHAT_ENDPOINT`/`HCHAT_DEPLOYMENT`는 SPEC 기본값 |

채팅 UI 상단의 키 입력란에 값을 넣으면 그 값이 우선 적용되고, 비우면 위 env 키가 폴백.

### 2) Elasticsearch

| 변수 | 설명 |
|------|------|
| `ES_HOSTS` | 단일 노드 또는 콤마 구분 멀티노드 (`https://es01:9200,https://es02:9200`) |
| `ES_USERNAME` / `ES_PASSWORD` | Basic Auth |
| `ES_VERIFY_CERTS` / `ES_CA_CERTS` | 자체 서명 인증서 처리 (기본: 검증 끔) |

자체 서명 인증서를 사용하면 `ES_VERIFY_CERTS=false` (기본값) 그대로 두거나,
사내 CA 번들 파일이 있으면 `ES_CA_CERTS=/path/to/ca.pem` 지정 + `ES_VERIFY_CERTS=true`.

`.env` 변경 후 서버를 재시작한 뒤 `/health`로 검증:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

`elasticsearch.reachable: true`, `indices.elasticsearch_docs: true`,
`indices.kafka_docs: true`, `llm.api_key_configured: true` 면 정상.

## 사내 용어와 브랜딩

배포 환경마다 달라지는 두 가지는 소스가 아니라 설정에 있습니다.

**`app/internal_terms.json`** — 사내에만 존재하는 고유명사 목록. 질문에 이
단어가 등장하면 LLM 판정과 무관하게 Confluence 인덱스를 검색 대상에 강제로
포함시킵니다. 특정 회사를 지목하는 정보라 **저장소에 포함되지 않고**,
`internal_terms.example.json`(플레이스홀더)만 추적됩니다. 파일을 만들지 않으면
예시 파일로 폴백해 기동은 되지만 이 라우팅은 사실상 동작하지 않습니다.
경로는 `INTERNAL_TERMS_FILE` 로도 지정할 수 있습니다. 자세한 카테고리 설명은
`OPERATIONS.md` Step 7 참조.

**`CHATBOT_NAME`** — UI 제목·헤더·로그인 카드·인트로 문구와 잡담/일반대화
페르소나에 함께 쓰이는 표시 명칭. 기본값은 `사내 문서 챗봇`입니다.

## Tests

```bash
uv run pytest -q
```

## Pipeline

```
query_analyze
  └─ chitchat → generate → END
  └─ search → query_decompose → query_rewrite (per sub-query)
            → metadata_extract → index_route (per sub-query)
            → hybrid_retrieve (RRF over BM25 + semantic_text)
            → self_check (retry up to RETRIEVAL_MAX_RETRY)
            → generate (streamed) → END
```

`index_route`는 각 sub-query별로 `elasticsearch_docs` / `kafka_docs` 중 어디를
검색할지 LLM에게 묻고, `hybrid_retrieve`가 zip해서 sub-query마다 자기
인덱스에만 검색합니다. 리랭커는 현재 미적용 (요청 시 추가 가능).

## API

- `GET /` — 내장 채팅 UI (HTML)
- `GET /info` — 서비스 메타데이터 (JSON)
- `GET /health` — ES 연결 + 인덱스 존재 + LLM 키 설정 여부 진단
- `GET /v1/models` — OpenAI 호환
- `POST /v1/chat/completions` — OpenAI 호환 SSE 스트리밍
