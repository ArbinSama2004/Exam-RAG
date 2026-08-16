"""Tests for application configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from examrag.config import Settings, get_settings


def test_defaults_are_local_development_friendly() -> None:
    settings = Settings()

    assert settings.app_name == "ExamRAG"
    assert settings.app_env == "local"
    assert settings.debug is False
    assert settings.api_port == 8000
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.upload_dir == Path("/data/uploads")


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("UPLOAD_DIR", "/tmp/examrag-uploads")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.postgres_host == "postgres"
    assert settings.upload_dir == Path("/tmp/examrag-uploads")


def test_cors_origins_accepts_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")

    assert Settings().cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_database_url_is_built_from_postgres_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_USER", "examrag")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "examrag")

    assert Settings().database_url == "postgresql+asyncpg://examrag:secret@postgres:5432/examrag"


def test_invalid_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
