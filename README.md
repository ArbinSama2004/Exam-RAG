# ExamRAG

A local, single-user RAG application for exam preparation. Upload your study
material and past question papers, then generate practice MCQs and discover the
questions that keep coming back.

> **Status: All four phases are complete.** Upload documents, generate
> RAG-grounded MCQ quizzes, take them with server-side scoring, inspect how
> each retrieval method performs on the same query, and find the exam
> questions that keep coming back across past papers. Phase 4 hardened
> crash recovery and error handling; see [Known limitations](#known-limitations).

## Features

- **Document upload** — PDF, DOCX, Markdown and TXT, each classified as
  `STUDY_MATERIAL` or `PAST_PAPER`, with live ingestion progress *(done)*
- **MCQ generator** — RAG-grounded practice quizzes with scoring and review
  *(done)*
- **Retrieval comparison** — vector, keyword, hybrid and reranked, side by side
  *(done)*
- **Past paper FAQ generator** — finds semantically repeated exam questions and
  how often they appear *(done)*

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
| Documents | PyMuPDF (PDF), python-docx (DOCX) |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`, 384-d), PyTorch CPU |
| Retrieval | pgvector + PostgreSQL full-text, RRF fusion, cross-encoder reranking |
| LLM | Ollama on the host |
| Database | PostgreSQL 17 with pgvector |
| Frontend | React, TypeScript, Vite, TanStack Query |
| Tooling  | uv, pytest, Ruff, mypy, Docker Compose, Make |

## Prerequisites

- Docker and Docker Compose
- [Ollama](https://ollama.com) on the host, for MCQ and answer generation
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

## API

| Endpoint | Purpose |
| -------- | ------- |
| `POST /documents` | Upload a PDF/DOCX/MD/TXT file with `purpose=STUDY_MATERIAL` or `PAST_PAPER`. Returns `202`. |
| `GET /documents` | List documents, newest first. Add `?purpose=` to filter. |
| `GET /documents/{id}` | One document and the model/chunker behind its chunks. |
| `GET /documents/{id}/status` | Ingestion status and stage — poll until `READY` or `FAILED`. |
| `POST /quizzes/generate` | Generate a quiz. Returns questions and options — never the answer key. |
| `POST /quizzes/{id}/answer` | Grade one answer and reveal the correct one. |
| `POST /quizzes/{id}/submit` | Final score and review. |
| `POST /retrieval/compare` | One query through vector, keyword, hybrid and reranked retrieval. |
| `POST /retrieval/answer` | A grounded answer with its sources. |
| `POST /faq/generate` | Questions extracted from past papers, grouped by meaning and ranked by how often they repeat. |
| `GET /health`, `GET /health/ready` | Liveness and readiness (readiness also reports the LLM). |

Try it:

```bash
curl -X POST http://localhost:8000/documents -F "file=@notes.pdf" -F "purpose=STUDY_MATERIAL"
```

Full interactive documentation is at http://localhost:8000/docs.

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
| `MAX_UPLOAD_MB` | `50` | Largest accepted upload |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend URL used by the frontend |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama on the host |
| `OLLAMA_MODEL` | `gpt-oss:20b-cloud` | Generation model — see the note below |
| `VECTOR_CANDIDATES` etc. | `30/30/30/20/6` | Retrieval tuning, adjustable during evaluation |

### Choosing a model

The default `gpt-oss:20b-cloud` is a **cloud** model: Ollama proxies it to
ollama.com, so your prompts — including passages retrieved from your documents
— leave this machine. It is fast and needs no local RAM.

To keep everything on your machine instead, pull a local model and point at it:

```bash
ollama pull llama3.1:8b
```

Then set `OLLAMA_MODEL=llama3.1:8b` in `.env`. Local generation needs enough
free RAM; on a memory-constrained machine an 8B model can be unusably slow.

## How to run

```bash
make up             # start everything with Docker Compose
make logs           # follow the logs
make down           # stop
make clean          # stop and delete the database volume
```

`make up` applies migrations and recovers any job orphaned by a previous crash
before the backend starts serving traffic — see
[docs/architecture.md](docs/architecture.md#upload-and-ingestion).

To run the services directly on your machine instead:

```bash
make setup          # install backend and frontend dependencies
make run-backend    # http://localhost:8000
make run-frontend   # http://localhost:3000
```

Set `POSTGRES_HOST=localhost` in `.env` when the backend runs outside Docker.

## How to run tests

```bash
make test           # backend pytest + frontend vitest
make lint           # Ruff + TypeScript
make typecheck      # mypy
make check          # all of the above
```

Tests that need PostgreSQL are skipped automatically when no database is
reachable, so `make test` works without Docker. Run `make up` first to include
them. Override the connection with `TEST_DATABASE_URL` if needed.

The suite never downloads the embedding model. To exercise the real one:

```bash
cd backend && EXAMRAG_TEST_REAL_MODEL=1 uv run pytest tests/embeddings
```

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
- Ingestion runs in FastAPI background tasks, so a document mid-job when the
  backend stops is orphaned. On the next start, before the API accepts
  traffic, `recover_interrupted_jobs` marks any job still `UPLOADED` or
  `PROCESSING` as `FAILED` — re-uploading the same file then retries it in
  place, the same as any other failed ingestion.
- The first upload downloads the embedding model (about 90 MB). It is cached on
  the `model_cache` volume afterwards.
- Embeddings run on CPU. The backend image is around 3.8 GB, most of it PyTorch.
- Past-paper question extraction is regex-based, matched to how numbered
  questions actually render in Markdown. An unusually formatted paper can miss
  or malform a question; it degrades one FAQ entry rather than the ingestion.
