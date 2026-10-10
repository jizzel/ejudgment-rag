"""Single source of configuration.

Precedence: environment variables > ``config/models.yaml`` > code defaults.
No other module may read ``os.environ`` directly; call :func:`get_settings`.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_YAML_PATH = REPO_ROOT / "config" / "models.yaml"


class ModelPrice(BaseModel):
    """USD per 1M tokens."""

    input: float = Field(ge=0.0)
    cached_input: float = Field(ge=0.0)
    output: float = Field(ge=0.0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        yaml_file=DEFAULT_YAML_PATH,
    )

    database_url: str = "postgresql+psycopg://ejudgment:ejudgment@localhost:5434/ejudgment"
    ingest_batch_size: int = Field(default=200, ge=1)

    # Local PDF verification against the legacy export's text.
    pdf_verify_pages: int = Field(default=2, ge=1)
    pdf_verify_min_window_chars: int = Field(default=10000, ge=1000)
    pdf_verify_min_overlap: float = Field(default=0.8, gt=0.0, le=1.0)

    # Chunking. Token counts use the embedding model's own tokenizer (no special tokens).
    tokenizer_model_id: str = "BAAI/bge-small-en-v1.5"
    tokenizer_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    chunk_target_tokens: int = Field(default=350, ge=50)
    chunk_max_tokens: int = Field(default=400, ge=50)

    # Text extraction for files without usable text (Homebrew: tesseract, poppler).
    tesseract_cmd: str = "tesseract"
    pdftoppm_cmd: str = "pdftoppm"
    ocr_dpi: int = Field(default=300, ge=72, le=600)
    ocr_language: str = Field(default="eng", pattern=r"^[a-z_+]{3,64}$")
    ocr_workers: int = Field(default=4, ge=1)
    ocr_min_confidence: float = Field(default=60.0, ge=0.0, le=100.0)

    # Embeddings (dense channel). The revision is pinned; weights load from the HF cache only.
    embedding_model_id: str = "BAAI/bge-small-en-v1.5"
    embedding_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    embedding_dimension: int = Field(default=384, ge=1)
    embedding_max_input_tokens: int = Field(default=512, ge=16)
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "
    embedding_batch_size: int = Field(default=64, ge=1)
    model_device: str = Field(default="auto", pattern=r"^(auto|cpu|mps|cuda)$")

    # Reranking.
    reranker_model_id: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_revision: str = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    reranker_max_input_tokens: int = Field(default=512, ge=16)
    rerank_top_n: int = Field(default=30, ge=1)

    # Hybrid retrieval. Pools are a fixed size so pagination is stable.
    hybrid_channel_k: int = Field(default=450, ge=10)
    rrf_k: int = Field(default=60, ge=1)
    hnsw_ef_search: int = Field(default=200, ge=10)
    # Nearest neighbours fetched before per-case capping. Fixed per request (stable pages);
    # 600 covered 211-381 distinct cases on real queries, above search_max_depth.
    dense_raw_neighbours: int = Field(default=600, ge=10)
    search_max_depth: int = Field(default=150, ge=1)
    # How long a count of embedded vs. eligible chunks is reused before recounting.
    embedding_coverage_ttl_seconds: float = Field(default=60.0, ge=0.0)

    # Search and API.
    source_base_url: str = "https://ghalii.org"
    search_max_top_k: int = Field(default=50, ge=1)
    passages_per_case: int = Field(default=3, ge=1)
    audit_store_raw_queries: bool = False

    # Sign-in (M4 slice 2). Every /v1 route needs a session unless auth_required is false
    # (tests of unrelated behaviour only; never in a deployment).
    auth_required: bool = True
    session_idle_hours: float = Field(default=12.0, gt=0.0)
    session_max_days: float = Field(default=7.0, gt=0.0)
    login_max_failures: int = Field(default=5, ge=1)
    login_window_minutes: float = Field(default=15.0, gt=0.0)
    password_min_length: int = Field(default=12, ge=8)
    # Salt for the client-IP and email hashes in auth_events. Without it a random per-process
    # salt is used, so hashes cannot be linked across restarts. Set it in .env, never in yaml.
    auth_hash_secret: SecretStr | None = None

    # Retention (worker.retention), in days.
    audit_retention_days: int = Field(default=90, ge=1)
    auth_event_retention_days: int = Field(default=365, ge=1)
    session_retention_days: int = Field(default=7, ge=1)
    usage_retention_days: int = Field(default=730, ge=1)

    # OpenAI (M3 slice 2): opt-in, generation only. The key comes from the environment or
    # .env (OPENAI_API_KEY), never from models.yaml. Limits are an application-side soft stop
    # per run (an evaluation run, or one UTC day of /v1/chat), not an account-level cap.
    openai_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = "gpt-6-luna"
    openai_reasoning_effort: str = Field(default="none", pattern=r"^(none|low|medium|high)$")
    openai_timeout_seconds: float = Field(default=60.0, gt=0.0)
    openai_max_retries: int = Field(default=1, ge=0, le=3)
    openai_max_output_tokens: int = Field(default=450, ge=16)
    openai_max_input_tokens: int = Field(default=5000, ge=500)
    openai_max_calls_per_run: int = Field(default=20, ge=1)
    openai_test_budget_usd: float = Field(default=1.0, gt=0.0)
    # USD per 1M tokens. A model without a price is refused (its cost cannot be estimated).
    openai_prices: dict[str, ModelPrice] = Field(default_factory=dict)

    # Proposition support: an NLI cross-encoder must find each claim entailed by a passage it
    # cites (labels are read from the model config). Pinned; weights come from fetch-models.
    nli_model_id: str = "cross-encoder/nli-deberta-v3-base"
    nli_revision: str = "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"
    nli_max_input_tokens: int = Field(default=512, ge=16)
    nli_min_entailment: float = Field(default=0.5, gt=0.0, lt=1.0)

    # Generation (M3). Local Ollama by default; the OpenAI provider comes in M3 slice 2.
    llm_provider: str = Field(default="ollama", pattern=r"^(ollama|openai)$")
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "gemma4:latest"
    ollama_num_ctx: int = Field(default=8192, ge=2048)
    llm_timeout_seconds: float = Field(default=180.0, gt=0.0)
    llm_max_output_tokens: int = Field(default=900, ge=64)
    # Context sent to the model: passages in retrieval order, capped per case and in total.
    generation_max_passages: int = Field(default=8, ge=1, le=20)
    generation_passages_per_case: int = Field(default=2, ge=1)
    generation_max_context_tokens: int = Field(default=4000, ge=500)
    # For an exact citation/case-name match, the judgment's last chunks (decision, orders).
    generation_case_closing_passages: int = Field(default=3, ge=0, le=10)
    generation_max_claims: int = Field(default=8, ge=1, le=20)
    # A claim survives only if it quotes at least this many words of a passage it cites.
    generation_min_quote_words: int = Field(default=4, ge=1)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
