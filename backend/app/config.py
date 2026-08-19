from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # User-facing chatbot name. Appears in the web UI title/header/intro and
    # in the chitchat + general-chat personas. Deployment branding, so it is
    # a setting rather than a literal scattered across prompts and HTML.
    chatbot_name: str = "사내 문서 챗봇"

    # ────── LLM provider switch ──────
    # "openai": public OpenAI (or any OpenAI-compatible base URL)
    # "azure":  Azure OpenAI, typically an internal corporate gateway
    llm_provider: Literal["openai", "azure"] = "azure"

    # Azure / internal gateway. No default endpoint on purpose: a real
    # gateway hostname is deployment infrastructure and does not belong in
    # source. Set HCHAT_ENDPOINT in .env when LLM_PROVIDER=azure.
    hchat_endpoint: str = ""
    hchat_deployment: str = "gpt-5.4-mini"
    hchat_api_version: str = "2024-02-01"
    hchat_api_key: str = ""

    # Public OpenAI (or compatible)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""  # set for OpenAI-compatible endpoints; empty = OpenAI default

    es_hosts: str = "https://localhost:9200"
    es_username: str = "elastic"
    es_password: str = "changeme"
    es_verify_certs: bool = False
    es_ca_certs: str | None = None  # path to CA bundle (optional, for self-signed)

    es_index_elasticsearch: str = "elasticsearch_docs"
    es_index_kafka: str = "kafka_docs"
    es_index_confluence: str = "confluence_docs"
    # Unified per-turn chat log index. user_id is a keyword field on each
    # document, not part of the index name, so debug_explain can filter by
    # user without operating on per-user indices.
    es_index_chat_logs: str = "chat_logs"
    # Per-user persistent instruction store. doc_id = user_id, one document
    # per user holding accumulated answer-style preferences as markdown.
    # Read on every answer node, written by the `instruction` intent path.
    es_index_chat_md: str = "chat_md"

    es_field_title: str = "title"
    es_field_content: str = "content"
    es_field_semantic: str = "content_embedding"
    es_field_url: str = "url"
    # Confluence-style page hierarchy ("ancestors[].title"). Indexed as
    # `ancestors.title` (object array → flattened sub-field). Searching this
    # lets a question about a parent section title surface child pages.
    # Other indices (elasticsearch_docs / kafka_docs) don't have this field;
    # the BM25 query uses `lenient: true` so it's silently ignored there.
    es_field_ancestors_title: str = "ancestors.title"

    retrieval_rank_window: int = 100
    retrieval_rank_constant: int = 60
    retrieval_top_k: int = 20
    # top_k schedule for the retrieval retry loop: attempt N (0-based) pulls
    # `retrieval_top_k_schedule[N]` docs, widening the net each re-search.
    # The list length is also the attempt budget — once all entries are
    # spent and self_check still says insufficient, the flow gives up and
    # generate produces the soft-escape redirect.
    retrieval_top_k_schedule: list[int] = [10, 20, 30]
    # Per-doc body cap shown to the answer LLM. Bigger means more context
    # reaches the LLM (and longer pages have a chance to surface their
    # actual answer body that was past the head section), at the cost of
    # input tokens. With top_k=20, total doc context ≈ char_limit × 20.
    generate_doc_char_limit: int = 5000
    # Per-doc excerpt shown to the self_check sufficiency judge. Smaller
    # than `generate_doc_char_limit` because the judge only needs enough
    # text to decide topical coverage, not write the answer. The previous
    # 200-char default was too narrow — confluence pages whose head 200
    # chars are menus / TOC produced false `sufficient=false` verdicts
    # even when rank-1 was the correct doc.
    self_check_doc_char_limit: int = 1000

    max_history_turns: int = 5

    backend_port: int = 8000
    log_level: str = "INFO"

    @property
    def active_api_key(self) -> str:
        """API key for the currently active LLM provider."""
        if self.llm_provider == "openai":
            return self.openai_api_key
        return self.hchat_api_key

    @property
    def llm_model_label(self) -> str:
        """Human-readable model identifier for the active provider."""
        if self.llm_provider == "openai":
            return self.openai_model
        return self.hchat_deployment

    @property
    def es_host_list(self) -> list[str]:
        """Split ES_HOSTS by comma to support multi-node clusters."""
        return [h.strip() for h in self.es_hosts.split(",") if h.strip()]

    @property
    def all_indices(self) -> list[str]:
        return [
            self.es_index_elasticsearch,
            self.es_index_kafka,
            self.es_index_confluence,
        ]

    @property
    def index_alias_map(self) -> dict[str, str]:
        return {
            "elasticsearch": self.es_index_elasticsearch,
            "kafka": self.es_index_kafka,
            "confluence": self.es_index_confluence,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
