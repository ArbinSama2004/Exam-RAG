# ExamRAG Backend

FastAPI backend for ExamRAG. Managed with [uv](https://docs.astral.sh/uv/) and Python 3.12.

## Layout

```text
src/examrag/
├── main.py           # FastAPI application factory (wiring only)
├── config.py         # Environment-driven settings
├── api/              # HTTP routers (health.py today)
├── database/         # Async engine, session factory, declarative Base
└── schemas/          # Pydantic request/response models
alembic/              # Database migrations
tests/                # pytest suite
```

Modules for `ingestion/`, `embeddings/`, `retrieval/`, `generation/` and `faq/`
are added in the phases that implement them.

## Local development

```bash
uv sync --extra dev
uv run uvicorn examrag.main:app --reload
```

Endpoints:

- `GET /health` — liveness, does not touch the database
- `GET /health/ready` — readiness, returns `503` when PostgreSQL is unreachable
- `GET /docs` — OpenAPI documentation

## Checks

```bash
uv run ruff format .
uv run ruff check .
uv run mypy
uv run pytest
```

## Migrations

Alembic reads the database URL from the application settings, so no URL is
stored in `alembic.ini`.

```bash
uv run alembic upgrade head
uv run alembic revision -m "description"
```
