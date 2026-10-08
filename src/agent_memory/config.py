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

    extraction_timeout_seconds: float = Field(default=15, gt=0)
    embedding_timeout_seconds: float = Field(default=10, gt=0)
    query_embedding_timeout_seconds: float = Field(default=3, gt=0, le=10)
    query_embedding_concurrency: int = Field(default=8, ge=1, le=100)
    query_embedding_cache_seconds: float = Field(default=60, gt=0, le=3600)
    query_embedding_cache_size: int = Field(default=256, ge=1, le=10000)
    worker_lease_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def validate_lease_budget(self) -> "Settings":
        if (
            max(self.extraction_timeout_seconds, self.embedding_timeout_seconds) + 5
            >= self.worker_lease_seconds
        ):
            raise ValueError("provider total timeout plus persistence margin must be below lease")
        return self

    service_name: str = "agent-memory"
    log_level: str = "INFO"
    log_json: bool = True
    trace_sample_ratio: float = Field(default=1, ge=0, le=1)
    trace_exporter: Literal["none", "console", "otlp"] = "none"
    metrics_exporter: Literal["none", "console", "otlp"] = "none"
