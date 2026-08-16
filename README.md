# ExamRAG

A local, single-user RAG application for exam preparation. Upload your study
material and past question papers, then generate practice MCQs and discover the
questions that keep coming back.

> **Status:** Phase 1 Tasks 1–2 are complete: project foundation and the
> database schema for documents, ingestion jobs and chunks. Document loading,
> chunking, embeddings, retrieval, MCQ generation and FAQ analysis are not
> implemented yet.

## Features

- **Document upload** — PDF, DOCX, Markdown and TXT, each classified as
  `STUDY_MATERIAL` or `PAST_PAPER` *(Phase 1)*
- **MCQ generator** — RAG-grounded practice quizzes with scoring and review
  *(Phase 2)*
- **Past paper FAQ generator** — finds semantically repeated exam questions and
  how often they appear *(Phase 3)*

## Architecture overview

```text
Upload → Markdown normalization → Chunking → Embeddings → PostgreSQL + pgvector

Query → Vector search + Keyword search → Fusion → Reranking → Context → LLM
```

See [docs/architecture.md](docs/architecture.md) for detail.

## Tech stack

| Layer    | Technology |
| -------- | ---------- |
| Backend  | Python 3.12, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 17 with pgvector |
| Frontend | React, TypeScript, Vite, TanStack Query |
| Tooling  | uv, pytest, Ruff, mypy, Docker Compose, Make |

## Prerequisites

- Docker and Docker Compose
- Optional, for running services outside Docker: [uv](https://docs.astral.sh/uv/)
  and Node.js 22

## Installation

```bash
git clone <repository>
cd ExamRAG
cp .env.example .env
make up
```

Then open:

```text
Frontend:          http://localhost:3000
Backend:           http://localhost:8000
API documentation: http://localhost:8000/docs
Health:            http://localhost:8000/health
```

`make up` builds the images, starts PostgreSQL with pgvector, applies the
database migrations and starts the backend and frontend.

## Environment variables

All variables live in `.env` (copied from `.env.example`). The defaults work
out of the box; the ones you are most likely to change are:

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `APP_ENV` | `local` | Application environment (`local` or `test`) |
| `DEBUG` | `false` | Enables debug mode and SQL echo |
| `LOG_LEVEL` | `INFO` | Backend log level |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `API_PORT` / `FRONTEND_PORT` | `8000` / `3000` | Host ports |
| `POSTGRES_*` | `examrag` | Database credentials, name, host and port |
| `UPLOAD_DIR` | `/data/uploads` | Upload path inside the container, bind-mounted to `./data/uploads` |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend URL used by the frontend |

## How to run

```bash
make up             # start everything with Docker Compose
make logs           # follow the logs
make down           # stop
make clean          # stop and delete the database volume
```

To run the services directly on your machine instead:

```bash
make setup          # install backend and frontend dependencies
make run-backend    # http://localhost:8000
make run-frontend   # http://localhost:3000
```

Set `POSTGRES_HOST=localhost` in `.env` when the backend runs outside Docker.

## How to run tests

```bash
make test           # pytest
make lint           # Ruff + TypeScript
make typecheck      # mypy
make check          # all of the above
```

Tests that need PostgreSQL are skipped automatically when no database is
reachable, so `make test` works without Docker. Run `make up` first to include
them. Override the connection with `TEST_DATABASE_URL` if needed.

## Project structure

```text
ExamRAG/
├── backend/            # FastAPI application (see backend/README.md)
│   ├── src/examrag/
│   ├── alembic/
│   └── tests/
├── frontend/           # React + Vite application
├── docs/               # Architecture, progress, decisions, concepts
├── data/uploads/       # Uploaded documents (bind-mounted into the backend)
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Development phases

| Phase | Scope |
| ----- | ----- |
| 1 | Project foundation and document ingestion |
| 2 | Complete hybrid RAG retrieval and the MCQ feature |
| 3 | Past paper FAQ generator and evaluation |
| 4 | Stabilization, optimization and documentation |

Progress is tracked in [docs/progress.md](docs/progress.md).

## Known limitations

- The application is local and single-user: there is no authentication and no
  multi-tenancy.
- Ingestion runs in FastAPI background tasks. If the backend stops mid-job, that
  job must be re-uploaded.
