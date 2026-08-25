# Hybrid RAG Chatbot

A chatbot that answers questions about internal documents **with the evidence
attached**. It sits on Elasticsearch, fuses BM25 and semantic search with RRF,
and the citation numbers in an answer point at documents that were actually
retrieved.

One idea drives the design: **answer quality is decided in retrieval, not in
generation.** So a question never goes straight to search. It is decomposed,
routed to an index, rewritten, searched, and checked for sufficiency — and when
the evidence is thin, the graph **searches again from a different angle**.

Stack:

- **FastAPI** — OpenAI-compatible API (`/v1/chat/completions`) with SSE streaming
- **LangGraph** — a 17-node query pipeline
- **Elasticsearch** — BM25 + `semantic_text` auto-embedding, fused via `retriever.rrf`
- **Built-in chat UI** — `GET /` serves inline HTML. No separate frontend process
- **LLM** — public OpenAI or an Azure internal gateway, switched with `LLM_PROVIDER`

## Quick start

```bash
cd backend
uv sync --all-extras
cp .env.example .env                                          # fill in the [required] entries
cp app/internal_terms.example.json app/internal_terms.json    # internal vocabulary, see below
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/`. Entering an ID on the login card appends
`?user_id=<id>`, which keeps conversation logs and answer-style preferences
separate per user.

Check the deployment after startup:

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

## Pipeline

```
query_analyze  ─ 6-intent classification
  ├─ chitchat    → generate
  ├─ general     → general_chat        (outside the internal-document scope)
  ├─ debugging   → debug_explain       ("why did you answer that?")
  ├─ instruction → instruction_save    ("keep your answers short from now on")
  ├─ re_search   → re_search_setup     ("not that one, look in Confluence")
  └─ question    → query_reform → search_intent
                     ├─ count → es_count
                     ├─ list  → es_list
                     └─ lookup → query_decompose → index_route → query_rewrite
                                 → metadata_extract → hybrid_retrieve
                                 → self_check ─┬─ enough → generate (streaming)
                                               └─ thin   → query_variate → retry
```

Why each stage exists:

- **`query_decompose`** — "compare ES and Kafka" is not a search query. It is two
  searches and one synthesis. Verbs like compare and summarise are split off from
  the search terms.
- **`index_route`** — every sub-query picks its own index, so a question about
  official docs does not scrape the internal wiki, and the other way round.
- **`query_rewrite`** — keywords for BM25 and noun phrases for semantic search are
  built **separately**. Inside RRF the two retrievers read different text.
- **`self_check` → `query_variate`** — when the evidence is thin the graph changes
  angle instead of repeating the same query, and widens the search following
  `RETRIEVAL_TOP_K_SCHEDULE`.

## Internal vocabulary and branding

The two things that differ per deployment live in configuration, not in source.

**`backend/app/internal_terms.json`** — proper nouns that exist only inside one
company (product names, acronyms, buildings, namespaces). When a question
contains one of them, the internal wiki index is forced into the search scope
regardless of what the LLM decides. A model cannot know a word used in a single
company, but the user's intent is unambiguous.

That list identifies a specific organisation, so **it is not in the repository.**
Only the placeholder `internal_terms.example.json` is tracked, and the app falls
back to it when the real file is missing. It still starts, but this routing is
effectively off and the startup log says so. `INTERNAL_TERMS_FILE` overrides the
path.

Operational phrases such as "in production" or "incident history" mean the same
thing at any company, so those stay in code. That split is the point of the
design.

**`CHATBOT_NAME`** — the display name used in the UI title, header, login card and
intro copy, and in the chitchat/general-conversation persona.

## Environment variables

See `backend/.env.example`. The ones you actually touch:

| Variable | Description |
|------|------|
| `LLM_PROVIDER` | `openai` (testing) or `azure` (internal gateway) |
| `OPENAI_API_KEY` / `HCHAT_API_KEY` | key for the chosen provider |
| `HCHAT_ENDPOINT` | internal gateway address. **No default in source** — required for azure |
| `ES_HOSTS` | single host or comma-separated multi-node |
| `ES_USERNAME` / `ES_PASSWORD` | basic auth |
| `RETRIEVAL_TOP_K_SCHEDULE` | top_k per retry. The list length is the retry budget |
| `CHATBOT_NAME` | display name |
| `INTERNAL_TERMS_FILE` | path to the internal vocabulary file (optional) |

## API

- `GET /` — built-in chat UI (HTML)
- `GET /info` — service metadata
- `GET /health` — ES connectivity, index existence, LLM key diagnostics
- `GET /v1/models` — OpenAI-compatible
- `POST /v1/chat/completions` — OpenAI-compatible SSE streaming

## Tests

```bash
cd backend && uv run pytest -q
```

154 of 155 pass. `test_instruction_save_no_user_id_skips_persistence` is a known
failure — the expected string and the implementation drifted apart.

Tests read the internal vocabulary from whichever file is active, so they verify
real routing on a configured deployment and still pass on a fresh clone that only
has the placeholder.

## Docs

- `SPEC.md` — nine rounds of design changes, and the current specification
- `backend/OPERATIONS.md` — runbook for adding a search index or editing a query
- `backend/README.md` — how to fill in each `.env` entry

## About

Built by [wny](https://github.com/shinwootag). I work on retrieval and knowledge
systems — hybrid document search here, ontology reasoning in
[human-networking-ontology](https://github.com/shinwootag/human-networking-ontology).
What interests me is the part after the answer appears: where it came from, and
whether a reader can check it.
