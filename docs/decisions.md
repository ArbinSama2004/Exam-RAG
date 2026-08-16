# Architecture Decisions

## PostgreSQL + pgvector

**Decision:** Use PostgreSQL with the pgvector extension instead of a separate
vector database.

**Reason:** The project needs relational storage (documents, chunks, ingestion
jobs, quiz sessions), full-text keyword search and vector similarity search.
pgvector provides vector search inside the database we already need, so hybrid
retrieval can join vector and keyword results without a second system to run,
back up and keep in sync.

**Date:** 2026-08-16

---

## Backend package layout `backend/src/examrag/`

**Decision:** Place backend code in the package `backend/src/examrag/` rather
than directly in `backend/src/`.

**Reason:** The specification's module boundaries are kept exactly (`api/`,
`database/`, `schemas/`, and later `ingestion/`, `retrieval/`, `generation/`,
`faq/`), but a named package gives unambiguous absolute imports
(`from examrag.config import ...`), makes the project installable by uv and
hatchling, and lets tests and Alembic import the application without sys.path
manipulation. The specification allows the structure to be adjusted where
implementation reveals a simpler organization.

**Date:** 2026-08-16

---

## Separate liveness and readiness endpoints

**Decision:** `GET /health` reports only that the API process is running.
`GET /health/ready` checks the database and returns `503` when it is
unreachable.

**Reason:** A single health endpoint that touches PostgreSQL cannot distinguish
"the backend is down" from "the database is down" — the first thing you want to
know when Compose starts up. Keeping liveness dependency-free also means the
frontend can show a meaningful message while the database is still starting.

**Date:** 2026-08-16

---

## Alembic reads its URL from application settings

**Decision:** `alembic.ini` contains no `sqlalchemy.url`; `alembic/env.py`
builds it from `Settings` and runs migrations through the async engine.

**Reason:** Credentials stay in one place (`.env`), there is no second DSN to
keep in sync, and the same asyncpg driver is used by the application and the
migrations.

**Date:** 2026-08-16

---

## Dependencies are added when the feature that uses them lands

**Decision:** Only FastAPI, Uvicorn, Pydantic v2, pydantic-settings,
SQLAlchemy (async), asyncpg and Alembic are installed today, with pytest,
pytest-asyncio, pytest-cov, httpx, Ruff and mypy for development.

**Reason:** The full stack is decided upfront, but installing PyMuPDF,
python-docx, sentence-transformers, NumPy and scikit-learn before their
features exist slows every install and Docker build and makes it unclear which
dependencies are actually in use. They are added in the tasks that need them.

**Date:** 2026-08-16
