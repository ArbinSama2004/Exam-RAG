# Development Progress

## Phase 1 — Project Foundation + Document Ingestion

### Completed

Task 1 — Project foundation (2026-08-16)

- [x] Repository structure (`backend/`, `frontend/`, `docs/`, `data/uploads/`)
- [x] uv project with `pyproject.toml`, committed `uv.lock`, Python 3.12 pinned
- [x] FastAPI backend skeleton (`main.py`, `config.py`, `api/`, `database/`, `schemas/`)
- [x] Frontend foundation (React, TypeScript, Vite, TanStack Query)
- [x] Docker Compose with `postgres`, `backend`, `frontend`
- [x] PostgreSQL 17 + pgvector image
- [x] Persistent `postgres_data` volume and `./data/uploads` bind mount
- [x] Alembic wired to the async engine, migration `0001` enables `vector`
- [x] `GET /health` and `GET /health/ready`
- [x] Tests for the health endpoints and configuration (13 passing)
- [x] Makefile, `.env.example`, initial documentation

### In Progress

- [ ] Task 2 — database entities and migrations (documents, chunks, embeddings,
      ingestion jobs)

### Not Started

- [ ] Task 3 — document loading and Markdown normalization (PDF, DOCX, MD, TXT)
- [ ] Task 4 — Markdown cleaning and chunking
- [ ] Task 5 — embedding generation and vector storage
- [ ] Task 6 — upload endpoint, ingestion jobs, background processing, duplicate protection
- [ ] Task 7 — frontend upload UI and status polling

### Problems

- None so far.

### Decisions

Recorded in [decisions.md](decisions.md):

- PostgreSQL + pgvector instead of a separate vector database
- Backend package layout `backend/src/examrag/`
- Split liveness and readiness health endpoints
- Alembic reads its URL from application settings
