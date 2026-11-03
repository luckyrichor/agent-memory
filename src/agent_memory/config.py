from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEMORY_", extra="forbid")

    database_url: str = (
        "postgresql+psycopg_async://agent_memory:local-development-only"
        "@localhost:55432/agent_memory"
    )
    jwt_public_key: str = ""
    jwt_issuer: str = ""
    jwt_audience: str = ""
    embedding_endpoint: str = ""
    embedding_protocol: Literal["openai", "ark"] = "openai"
    embedding_trust_env: bool = True
    embedding_model: str = ""
    embedding_token: SecretStr = SecretStr("")
    extraction_endpoint: str = ""
    extraction_model: str = ""
    extraction_token: SecretStr = SecretStr("")
    extraction_trust_env: bool = False
    # auto: low-risk extracted candidates become retrievable at once; manual: wait for review.
    candidate_activation: Literal["auto", "manual"] = "auto"

    extraction_timeout_seconds: float = Field(default=15, gt=0)
    embedding_timeout_seconds: float = Field(default=10, gt=0)
    query_embedding_timeout_seconds: float = Field(default=3, gt=0, le=10)
    query_embedding_concurrency: int = Field(default=8, ge=1, le=100)
    query_embedding_cache_seconds: float = Field(default=60, gt=0, le=3600)
    query_embedding_cache_size: int = Field(default=256, ge=1, le=10000)
    worker_lease_seconds: float = Field(default=30, gt=0)
    # API connection pool. Defaults used to be SQLAlchemy's (5 + 10 overflow, 30 s wait): when the
    # pool was exhausted a request hung 30 s and then failed with an opaque 500 (B0 finding F2).
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_pool_timeout_seconds: float = Field(default=2, gt=0, le=30)
    db_statement_timeout_ms: int = Field(default=15000, ge=0, le=600000)  # 0 = no limit
    # Rows each retrieval channel may contribute before fusion. Deep pagination (offset up to
    # 2900) needs the default; lower it only with recall data from the dev set (PLAN.md B1).
    retrieval_candidate_limit: int = Field(default=1000, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_lease_budget(self) -> "Settings":
        if (
            max(self.extraction_timeout_seconds, self.embedding_timeout_seconds) + 5
            >= self.worker_lease_seconds
        ):
            raise ValueError("provider total timeout plus persistence margin must be below lease")
        return self

    max_request_body_bytes: int = Field(default=1_048_576, ge=1024, le=8_388_608)

    service_name: str = "agent-memory"
    log_level: str = "INFO"
    log_json: bool = True
    trace_sample_ratio: float = Field(default=1, ge=0, le=1)
    trace_exporter: Literal["none", "console", "otlp"] = "none"
    metrics_exporter: Literal["none", "console", "otlp"] = "none"
