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
- [x] Tests for the health endpoints and configuration
- [x] Makefile, `.env.example`, initial documentation

Task 2 — Database entities and migrations (2026-08-16)

- [x] Domain enums: `DocumentPurpose`, `DocumentType`, `ProcessingStatus`, `IngestionStage`
- [x] `documents` table with purpose, status, hashes, embedding model and chunker version
- [x] `ingestion_jobs` table with status, stage, error message and timing
- [x] `chunks` table with content, source metadata, `vector(384)` embedding and
      a generated `content_tsv`
- [x] HNSW index for vector search, GIN index for keyword search
- [x] `ON DELETE CASCADE` from documents to chunks and jobs
- [x] Metadata naming convention for stable migrations
- [x] Migration `0002`; `alembic check` reports no drift
- [x] 22 new tests (12 model-level, 10 against a real database, auto-skipped
      when none is reachable) — 35 passing in total

### In Progress

- [ ] Task 3 — document loading and Markdown normalization (PDF, DOCX, MD, TXT)

### Not Started

- [ ] Task 4 — Markdown cleaning and chunking
- [ ] Task 5 — embedding generation and vector storage
- [ ] Task 6 — upload endpoint, ingestion jobs, background processing, duplicate protection
- [ ] Task 7 — frontend upload UI and status polling

### Problems

- `pydantic-settings` JSON-decodes list-typed fields before validators run, so
  `CORS_ORIGINS` as a comma-separated string raised `SettingsError`. Fixed by
  annotating the field with `NoDecode` (Task 1).
- Reusing one `Enum` type across two tables makes SQLAlchemy attempt
  `CREATE TYPE` twice. Migration `0002` creates every enum type explicitly up
  front instead (Task 2).

### Decisions

Recorded in [decisions.md](decisions.md):

- PostgreSQL + pgvector instead of a separate vector database
- Backend package layout `backend/src/examrag/`
- Split liveness and readiness health endpoints
- Alembic reads its URL from application settings
- Embeddings stored as a column on `chunks`, not in a separate table
- `content_tsv` as a database-generated column
- Embedding dimensionality as a code constant, not a setting
- Documents unique per `(file hash, purpose)`
