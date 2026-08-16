"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for the ExamRAG backend."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ExamRAG"
    app_version: str = "0.1.0"
    app_env: Literal["local", "test"] = "local"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "examrag"
    postgres_password: str = "examrag"
    postgres_db: str = "examrag"

    upload_dir: Path = Path("/data/uploads")
    max_upload_mb: int = 50

    # Retrieval tuning. Unlike the embedding model or chunker version, these
    # are read at query time and affect nothing already stored, so they are
    # environment variables that can be adjusted during evaluation.
    vector_candidates: int = 30
    keyword_candidates: int = 30
    fused_candidates: int = 30
    reranker_candidates: int = 20
    final_context_chunks: int = 6

    # LLM generation through Ollama.
    #
    # The default is a `-cloud` model, which Ollama proxies to ollama.com: the
    # prompt, and therefore the retrieved study material, leaves the machine.
    # A local model keeps everything on the machine but needs the RAM to run
    # it — set OLLAMA_MODEL to something like llama3.1:8b and pull it first.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b-cloud"
    llm_temperature: float = 0.2
    llm_context_tokens: int = 8192
    llm_timeout_seconds: float = 180.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so the value is easy to set in .env."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def database_url(self) -> str:
        """Async DSN used by the application and by Alembic (SQLAlchemy + asyncpg)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
