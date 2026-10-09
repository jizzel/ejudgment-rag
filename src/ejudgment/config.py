"""Single source of configuration.

Precedence: environment variables > ``config/models.yaml`` > code defaults.
No other module may read ``os.environ`` directly; call :func:`get_settings`.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_YAML_PATH = REPO_ROOT / "config" / "models.yaml"


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
