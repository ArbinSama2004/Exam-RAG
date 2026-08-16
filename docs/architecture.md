# Architecture

This document describes the target architecture and marks what is implemented
today. It is updated as each task lands.

## System overview

```text
React frontend (Vite, TanStack Query)
          │  HTTP / JSON
          ▼
FastAPI backend
          │
          ▼
PostgreSQL 17 + pgvector
```

Three Docker Compose services: `postgres`, `backend`, `frontend`. No worker,
queue or cache service — ingestion uses FastAPI background tasks and stores job
state in PostgreSQL.

## Backend module boundaries

| Module | Responsibility | Status |
| ------ | -------------- | ------ |
| `main.py` | Application factory: settings, logging, CORS, routers, lifespan | Implemented |
| `config.py` | Environment-driven settings, database URL construction | Implemented |
| `api/` | HTTP routers; thin, delegating to services | `health.py` implemented |
| `database/` | Async engine, session factory, declarative `Base`, ORM models | Connection layer implemented |
| `schemas/` | Pydantic request/response models | `health.py` implemented |
| `ingestion/` | Loading, Markdown normalization, cleaning, chunking | Phase 1, later tasks |
| `embeddings/` | Embedding generation | Phase 1, later tasks |
| `retrieval/` | `base`, `vector_search`, `keyword_search`, `fusion`, `reranker` | Phase 2 |
| `rag/` | Orchestration: pipeline and context building | Phase 2 |
| `generation/` | LLM client, prompt building, MCQ and answer generation | Phase 2 |
| `faq/` | Question extraction, normalization, clustering, frequency analysis | Phase 3 |

`main.py` contains no pipeline logic. Business logic stays out of route
handlers.

## Configuration

`Settings` (pydantic-settings) reads environment variables and, when present,
`.env`. It exposes `database_url`, built from the `POSTGRES_*` values, so no
DSN is duplicated across the codebase. `get_settings()` is cached and injected
into routes as a FastAPI dependency, which makes it overridable in tests.

## Database access

`database/connection.py` owns a lazily created async engine and
`async_sessionmaker`. Routes receive a session through the `get_session`
dependency; tests override that dependency instead of touching a real database.
`Base` is the single declarative base, and Alembic autogeneration reads its
metadata.

## Migrations

Alembic runs against the async engine. `alembic/env.py` imports the application
settings, so `alembic.ini` holds no credentials. Migration `0001` enables the
`vector` extension; the ingestion tables follow in the next task.

## Health endpoints

| Endpoint | Behavior |
| -------- | -------- |
| `GET /health` | Liveness. Returns app name, version and environment. Never touches the database, so it stays useful while PostgreSQL is down. |
| `GET /health/ready` | Readiness. Runs `SELECT 1`; returns `503` with `{"status": "not_ready", "database": "unavailable"}` when the database is unreachable. |

## Frontend structure

```text
src/
├── main.tsx        # React root
├── App.tsx         # QueryClientProvider and page composition
├── pages/          # Screen-level components
├── components/     # Reusable UI pieces
└── services/api.ts # Typed backend calls and base URL
```

TanStack Query owns server state, which is what the Phase 1 ingestion-status
polling will build on.

## Extension points

- **Retrieval strategies** — Phase 2 introduces a `Retriever` interface so a
  future `GraphRetriever` can be added without touching orchestration, the API
  or the frontend. No graph code or dependency exists today.
- **Embedding and reranking models** — recorded per document (model name,
  chunker version) so stored vectors stay traceable when a model changes.
- **Retrieval tuning** — candidate counts become environment variables in
  Phase 2, so evaluation does not require code changes.
