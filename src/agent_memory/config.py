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
