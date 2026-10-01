"""Application settings, loaded from the repo-root `.env` (see `.env.example`)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allow_origins: str = "http://localhost:5173"
    portal_base_url: str = "http://localhost:5173"

    anthropic_api_key: str = ""
    claude_model: str = ""

    database_url: str = "sqlite:///./data/portal.db"
    seed_db_path: str = "./seed/seed.db"
    file_storage_path: str = "./data/files"

    smtp_host: str = "localhost"
    smtp_port: int = 1025

    mock_latency_ms: int = 0
    mock_failure_rate: float = 0.0

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
