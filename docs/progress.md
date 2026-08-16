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

Task 3 — Document loading and Markdown normalization (2026-08-16)

- [x] `DocumentPage` / `LoadedDocument` as the shared normalized representation
- [x] PDF loading through PyMuPDF, one Markdown page per PDF page
- [x] Heading inference from relative font size, plus short bold lines
- [x] Bullet glyphs converted to Markdown list items
- [x] DOCX loading through python-docx: heading, list and quote styles, tables
- [x] Paragraph and table order preserved from the document body XML
- [x] Markdown and TXT loading with UTF-8 then CP-1252 decoding, BOM stripped
- [x] `DocumentLoadError` and `UnsupportedDocumentTypeError` for the upload endpoint
- [x] 42 tests building real PDF and DOCX files — 77 passing in total

Task 4 — Markdown cleaning and chunking (2026-08-16)

- [x] Dehyphenation across line breaks, including across separate text blocks
- [x] Reflow of prose wrapped mid-sentence, preserving structural line breaks
- [x] Page-number, control-character and exotic-space removal
- [x] Running header/footer detection by comparing pages
- [x] Fenced code blocks passed through untouched
- [x] Structure-aware chunking with heading breadcrumbs and page numbers
- [x] Sentence-aligned overlap, oversized-block splitting, short-chunk merging
- [x] `CHUNKER_VERSION` recorded so stale chunks stay detectable
- [x] End-to-end composition test over a real PDF
- [x] 47 new tests — 124 passing in total

Task 5 — Embedding generation and vector storage (2026-08-16)

- [x] `EmbeddingGenerator` over sentence-transformers, model loaded on first use
- [x] `Encoder` protocol so tests never download a model
- [x] L2-normalized 384-dimensional vectors, batched
- [x] Model width validated against the schema at load; output shape per call
- [x] `vector_store.replace_chunks` writes chunks and vectors as a set
- [x] Provenance (`chunk_count`, `embedding_model`, `chunker_version`) recorded together
- [x] Opt-in real-model test (`EXAMRAG_TEST_REAL_MODEL=1`)
- [x] `model_cache` volume so the model downloads once
- [x] CPU-only torch wheels on Linux: backend image 17.7 GB to 3.78 GB
- [x] 24 new tests — 148 passing in total

Task 6 — Upload endpoint, jobs, background processing, duplicates (2026-08-16)

- [x] `POST /documents` with required `STUDY_MATERIAL` / `PAST_PAPER` purpose
- [x] `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/status`
- [x] File storage keyed by document id, with SHA-256 hashing
- [x] Ingestion pipeline: load, clean, chunk, embed, index
- [x] FastAPI background processing in its own session, queued after commit
- [x] Stage committed as it starts, so polling shows real progress
- [x] Failures recorded as `FAILED` with the exception message
- [x] Duplicate uploads reused; failed ones retried in place
- [x] Validation: unsupported type and empty file `400`, oversized `413`
- [x] `MAX_UPLOAD_MB` setting
- [x] 30 new tests — 178 passing in total

### In Progress

- [ ] Task 7 — frontend upload UI and status polling

### Not Started

### Problems

- `pydantic-settings` JSON-decodes list-typed fields before validators run, so
  `CORS_ORIGINS` as a comma-separated string raised `SettingsError`. Fixed by
  annotating the field with `NoDecode` (Task 1).
- Reusing one `Enum` type across two tables makes SQLAlchemy attempt
  `CREATE TYPE` twice. Migration `0002` creates every enum type explicitly up
  front instead (Task 2).
- CP-1252 defines almost every byte, so the text decoding fallback rarely
  fails. That is acceptable for user-supplied text files, but it means
  `DocumentLoadError` for undecodable text is a narrow case (Task 3).
- PyMuPDF ships incomplete type annotations, so `pdf_to_markdown` needs a
  narrow mypy override for untyped calls (Task 3).
- The end-to-end composition test found two integration bugs the unit tests
  missed: the PDF renderer joined paragraph lines with spaces, which destroyed
  the line structure the cleaner needs to dehyphenate and to spot page numbers;
  and chunk overlap could push a chunk past `MAX_CHUNK_CHARS`. Both fixed in
  Task 4.
- Header detection originally took the first and last two lines of each page,
  which overlap on a short page and deleted mid-page content. The slices are
  now capped so they can never meet (Task 4).
- The default Linux torch wheels bundle CUDA, which made the backend image
  17.7 GB. Declaring torch explicitly and pointing it at the CPU-only wheel
  index for Linux brought it to 3.78 GB (Task 5).
- sentence-transformers 5.x renamed `get_sentence_embedding_dimension` to
  `get_embedding_dimension`; the minimum version is pinned to 5.0 and the
  protocol uses the current name (Task 5).
- Reprocessing a failed upload first tried to create a second document row,
  which the `(file hash, purpose)` unique constraint forbids. Failed documents
  are now retried in place (Task 6).
- Coverage under-reported every route handler — 64% for `upload.py` — because
  SQLAlchemy's async layer switches greenlets and loses the tracer. Adding
  `concurrency = ["thread", "greenlet"]` to the coverage config reported the
  true 99% (Task 6).
- PostgreSQL's `now()` is the transaction start time, so rows written in one
  transaction share a `created_at`. Only affects tests; each real upload has
  its own transaction (Task 6).

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
- Markdown as the normalized representation, with page numbers preserved
- Heading inference from font metrics for PDF, explicit styles for DOCX
- Structure-aware chunking with heading breadcrumbs
- Chunk sizing as code constants tied to `CHUNKER_VERSION`
- Embedding model as a constant, validated against the schema at load
- Chunk writes centralized in `vector_store`, replacing rather than appending
- Duplicate uploads reused, failed ones retried in place
- Ingestion progress committed per stage so polling is meaningful
