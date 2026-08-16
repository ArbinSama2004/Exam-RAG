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
| `api/` | HTTP routers; thin, delegating to services | `health.py`, `upload.py` implemented |
| `database/` | Async engine, session factory, ORM models, chunk/vector storage | Implemented |
| `enums.py` | Domain enumerations shared by models, schemas and API | Implemented |
| `schemas/` | Pydantic request/response models | `health.py`, `document.py` implemented |
| `ingestion/` | Loading, normalization, cleaning, chunking, file storage, pipeline | Implemented |
| `embeddings/` | Embedding generation | Implemented |
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

## Document loading and normalization

```text
PDF ──► pdf_to_markdown  ─┐
DOCX ─► docx_to_markdown ─┼─► LoadedDocument ─► markdown_cleaner ─► chunker ─► [TextChunk]
MD/TXT ───────────────────┘
```

`document_loader.py` is the single entry point. It resolves the format from the
file extension and delegates; it performs no conversion itself.

Every format produces the same shape — a `LoadedDocument` holding ordered
`DocumentPage` values, each with Markdown and an optional page number. Page
numbers are captured here because this is the last point at which the source
layout is known, and chunk-level source attribution depends on them. Formats
without pagination (DOCX, Markdown, TXT) produce a single page with
`number = None`, so nothing downstream has to invent one.

| Module | Approach |
| ------ | -------- |
| `pdf_to_markdown.py` | PyMuPDF. A PDF has no structure, only positioned text, so headings are inferred: the body font size is the most common size weighted by character count, and a line is a heading when its font is proportionally larger, or when it is entirely bold and short. Bullet glyphs become list items. One Markdown page per PDF page. |
| `docx_to_markdown.py` | python-docx. DOCX carries real structure, so nothing is inferred: `Heading N`, `Title`, `Subtitle`, list and quote styles map directly to Markdown. Tables become Markdown tables. Paragraphs and tables are read from the document body in XML order, because python-docx exposes them as separate collections that lose their relative order. |
| `document_loader.py` | Markdown passes through unchanged; plain text is treated as Markdown without markup. Decoding tries UTF-8 then CP-1252, and a UTF-8 BOM is stripped. |

Failures raise `DocumentLoadError`, or `UnsupportedDocumentTypeError` for an
extension outside PDF/DOCX/MD/TXT — the two exceptions the upload endpoint will
translate into responses.

### Cleaning

`markdown_cleaner.py` removes what conversion leaves behind, so artefacts are
never embedded as if they were content:

- words hyphenated across a line break are rejoined, including when the halves
  land in separate text blocks
- prose wrapped mid-sentence is reflowed; headings, list items, table rows and
  quotes keep their line breaks because those breaks carry meaning
- page-number lines, control characters and exotic spaces are dropped
- a running header or footer is detected by comparing pages and removed

Header detection only considers lines at the top and bottom of a page, and the
head and tail slices never overlap, so mid-page content is never mistaken for a
header on a short page. It needs at least three pages before it will act.

Fenced code blocks pass through untouched, since whitespace is significant
inside them.

### Chunking

`chunker.py` produces `TextChunk` values — index, content, page number and
heading breadcrumb — using structure rather than a fixed window:

- a heading starts a new chunk, so a section's content never leaks into the
  previous one
- the heading path is recorded as a breadcrumb (`OSI Model > Physical Layer`),
  which is what Phase 2 uses to spread all-topics MCQ generation across
  sections instead of over one global context
- a heading with no content of its own is folded into the following chunk
- consecutive chunks overlap by `OVERLAP_CHARS`, cut on a sentence boundary
- oversized blocks split on sentences, then hard-split if they still do not fit
- chunks below `MIN_CHUNK_CHARS` merge into their neighbour, but only under the
  same heading

`CHUNKER_VERSION` identifies the strategy and is stored per document, so chunks
produced by an older version stay detectable. It must be bumped whenever the
algorithm or any of its size constants change.

## Embeddings

`embeddings/embedding_generator.py` wraps sentence-transformers behind an
`Encoder` protocol. One model serves both sides of retrieval — chunks at
ingestion, queries at search time — because vectors from different models are
not comparable.

| Aspect | Choice |
| ------ | ------ |
| Model | `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions |
| Loading | Deferred to first use; a fresh install downloads the model |
| Normalization | L2, so cosine distance in pgvector is a dot product |
| Batching | 32 texts per forward pass |
| Safety | The model's width is checked against `EMBEDDING_DIMENSIONS` at load, and the output shape is checked per call |

Depending on a protocol rather than the concrete class keeps the test suite free
of a model download; the real model is covered by an opt-in test
(`EXAMRAG_TEST_REAL_MODEL=1`).

In Docker the model is cached on the `model_cache` volume, so it downloads once
rather than on every container start. Torch is installed from the CPU-only
wheel index on Linux — the default wheels bundle CUDA and made the backend
image 17.7 GB instead of 3.8 GB.

## Vector storage

`database/vector_store.py` is the only module that writes to `chunks`, so the
rules that make a document retrievable live in one place:

- `replace_chunks` writes a document's chunks and vectors as a set, deleting any
  it already had. Replacing rather than appending means re-ingestion cannot
  leave orphaned chunks that retrieval would still return.
- It records `chunk_count`, `embedding_model` and `chunker_version` on the
  document in the same call, so a document always states what produced its
  vectors.
- `count_embedded_chunks` distinguishes chunks that carry a vector from those
  that do not, since a chunk without one is invisible to vector search.

The caller owns the transaction. Retrieval reads belong to the `retrieval`
package and arrive in Phase 2.

## Upload and ingestion

```text
POST /documents ─► validate ─► hash ─► store file ─► Document + IngestionJob ─► 202
                                                              │
                                            BackgroundTasks ──┘
                                                              ▼
                        load → clean → chunk → embed → index → READY
                                                              │
GET /documents/{id}/status ◄───── polled by the frontend ─────┘
```

| Endpoint | Purpose |
| -------- | ------- |
| `POST /documents` | Upload a file with its purpose. Returns `202` with the document and job id. |
| `GET /documents` | List documents, newest first, optionally filtered by purpose. |
| `GET /documents/{id}` | One document, including the model and chunker that produced its chunks. |
| `GET /documents/{id}/status` | Current status and stage. This is the polling endpoint. |

The route handler validates, decides whether the upload is a duplicate, and
hands the work to a background task. It runs no pipeline logic itself.

Validation rejects unsupported extensions (`400`), empty files (`400`) and
uploads over `MAX_UPLOAD_MB` (`413`).

### Background processing

`ingestion_pipeline.process_document` opens its own session, because the
request's session is closed once the response is sent. The task is queued only
after the upload transaction commits, so it cannot look for a row that has not
been written.

Each stage is committed as it starts, which is what makes the status endpoint
useful — a poller sees `CHUNKING` while chunking is happening, not a single
jump from `UPLOADED` to `READY`. Failures are recorded as `FAILED` with the
exception type and message rather than raised: a background task has nobody to
raise to, and the frontend polls for exactly this.

### Duplicate protection

An upload is hashed before anything else is stored. If a document already
exists with that `(file hash, purpose)`:

- it is **reused** — returned as-is with `reused: true`, generating no
  embeddings — unless its last ingestion failed;
- a **failed** document is **retried in place**: the file is written again, the
  status resets to `UPLOADED` and a new job is queued. A second row is
  impossible anyway, since `(original_file_hash, purpose)` is unique, and
  retrying in place keeps the document id the frontend already holds. Writing
  the file again also recovers a document whose upload volume was cleared.

## Data model

```text
documents 1───n ingestion_jobs
    │
    └───n chunks (embedding vector(384), content_tsv tsvector)
```

**`documents`** — one uploaded file. Carries `purpose`
(`STUDY_MATERIAL` / `PAST_PAPER`), `status`, `stored_path`, `size_bytes` and
the provenance fields required for duplicate protection:
`original_file_hash`, `normalized_content_hash`, `embedding_model` and
`chunker_version`. The last three are nullable because they are only known
once ingestion has run. `UNIQUE (original_file_hash, purpose)` blocks
re-embedding an unchanged file while still allowing the same file to be
registered under each purpose.

**`ingestion_jobs`** — one processing attempt per row, holding `status`
(`UPLOADED` → `PROCESSING` → `READY` / `FAILED`), a finer-grained `stage` for
the progress display, `error_message`, and start/finish timestamps. Job state
lives in PostgreSQL so the frontend can poll it and a crashed run stays
visible.

**`chunks`** — a retrievable slice of normalized Markdown plus the metadata
that makes an answer traceable: `chunk_index`, `page_number`, `heading`,
`char_count`. Both retrieval representations sit on the row:

- `embedding vector(384)` with an HNSW index using `vector_cosine_ops`
- `content_tsv tsvector`, a stored generated column over
  `to_tsvector('english', content)`, with a GIN index

Chunks and jobs are deleted with their document via `ON DELETE CASCADE`.

## Migrations

Alembic runs against the async engine. `alembic/env.py` imports the application
settings, so `alembic.ini` holds no credentials. `Base.metadata` uses an
explicit naming convention, so constraint and index names are deterministic
rather than database-assigned, and autogenerated migrations stay stable.

| Revision | Contents |
| -------- | -------- |
| `0001` | Enables the `vector` extension |
| `0002` | Creates `documents`, `ingestion_jobs`, `chunks` and their enum types |

`alembic check` reports no drift between the models and the migrated schema.

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
