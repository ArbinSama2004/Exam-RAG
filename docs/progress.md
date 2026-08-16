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

## Phase 2 — Complete RAG Retrieval + MCQ Feature

### Completed (2026-08-16)

- [x] `Retriever` interface, `RetrievedChunk`, shared selection filters
- [x] Vector search through pgvector; keyword search through `tsvector`
- [x] Past papers excluded from answer evidence unless requested
- [x] Reciprocal Rank Fusion over ranks
- [x] Cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`)
- [x] `RagPipeline` with a `RetrievalTrace` keeping every stage's output
- [x] Context builder: numbered, attributed passages within a budget
- [x] `LLMClient` protocol with an Ollama implementation over httpx
- [x] Prompt builder for grounded answers and MCQs
- [x] MCQ generation distributed across document sections
- [x] Output validation, deduplication, citation resolution
- [x] Quiz tables and migration `0003`; answer key stays server-side
- [x] `POST /quizzes/generate`, `/answer`, `/submit`; one answer per question
- [x] `POST /retrieval/compare` and `/retrieval/answer`
- [x] Retrieval tuning values as environment variables
- [x] Frontend: tabs, MCQ setup, quiz, review, retrieval comparison
- [x] 116 new backend tests and 17 new frontend tests

### Verified end to end

- Retrieval comparison over a real document: the reranker scored an irrelevant
  chunk at −9.02 while the relevant one scored +4.82
- Quiz generated in 43 s with `gpt-oss:20b-cloud`, one question per section
- Answering revealed the key only after committing; re-answering returned 409
- The generated quiz response contained no `correct_index` or `explanation`

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
- Ingestion progress froze in the browser: TanStack Query pauses
  `refetchInterval` while the window is unfocused, and this app disables
  refetch-on-focus. Fixed with `refetchIntervalInBackground` (Task 7).
- Testing Library's `upload` honours the input's `accept` attribute, so a test
  that expected the backend to reject a `.pptx` never got that far. The picker
  filters it first; the test now covers a real backend rejection (Task 7).
- The first live quiz generation died with "the underlying connection is
  closed": the endpoint held a database transaction open across three model
  calls, and the idle connection was dropped. Generation is now split into a
  database phase and a model phase, with the transaction released between them
  (Phase 2).
- `llama3.1:8b` ran at 0.4 tokens/second on this machine and timed out at 180 s
  per section. Switched to `gpt-oss:20b-cloud`, which completes a three-section
  quiz in 43 s — but it is proxied to ollama.com, so prompts leave the machine
  (Phase 2).
- `httpx` was declared as a dev dependency while `llm_client.py` imports it at
  runtime. It only worked because the image installed dev extras; moved to the
  runtime dependencies (Phase 2).
- The embedding model was loading twice — once for ingestion's module-level
  instance and once for the API dependency. Both now share one instance
  (Phase 2).

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
- Frontend polls in the background and stops at a terminal status
- Retrieval components behind one interface, fusion over ranks
- MCQ generation split into a database phase and a model phase
- Quizzes stored server-side so the answer key never reaches the browser early

## Phase 3 — Past Paper FAQ Generator and Evaluation

### Completed (2026-08-16)

- [x] `faq/question_extractor.py` — marker-anchored extraction over stored
      chunk content, reusing `markdown_cleaner`'s structural-line preservation
- [x] `faq/question_normalizer.py` — strips mark/point allocations, folds
      curly quotes and dashes, collapses whitespace
- [x] `faq/question_clusterer.py` — greedy nearest-centroid cosine clustering
      over numpy, no new dependency
- [x] `faq/faq_pipeline.py` — orchestration: query READY past papers, extract,
      normalize, embed, cluster, rank by occurrence count
- [x] `POST /faq/generate` — scoped to specific past papers or all of them,
      with a `min_occurrences` filter; recomputes on every call
- [x] Frontend: `FaqGenerator.tsx` — select past papers, choose a minimum
      repeat count, ranked results with expandable sources and variants
- [x] Evaluation: a hand-labeled set of 15 past-paper-style questions (4
      groups of paraphrased repeats, 5 distractors), scored with pairwise
      precision/recall/F1 against the real embedding model
- [x] 40 new backend tests (unit: extractor, normalizer, clusterer; database:
      pipeline query and filtering; API: `/faq/generate`; evaluation: opt-in
      real-model clustering quality) and 7 new frontend tests

### Verified end to end

- Clustering evaluation at `DEFAULT_SIMILARITY_THRESHOLD = 0.83`: precision
  1.00, recall 0.88, F1 0.93 over the 15-question labeled set, run with
  `EXAMRAG_TEST_REAL_MODEL=1` against the real `all-MiniLM-L6-v2` model
- Full backend suite (`uv run pytest`) and frontend suite (`npm run test`)
  pass, alongside `ruff format --check`, `ruff check`, `mypy` and `tsc --noEmit`

### Problems

- Numbered exam questions are not converted into Markdown list items by
  `pdf_to_markdown` (only glyph bullets are); they were expected to need a
  bespoke parser. They turned out to already be recoverable because
  `markdown_cleaner._STRUCTURAL_LINE` preserves any line starting with
  `\d+[.)]\s` for the same reason it preserves list items — extraction reuses
  that instead of adding a second heuristic.
- A hash-based fake encoder (identical text → identical vector, otherwise
  orthogonal) is enough to test the pipeline's plumbing — filtering, scoping,
  ranking — but cannot test whether real paraphrases actually cluster
  together. That question needed its own opt-in test against the real model,
  which is also Phase 3's evaluation deliverable.

### Decisions

Recorded in [decisions.md](decisions.md):

- FAQ extraction relies on the cleaner's structural-line rule, not a new parser
- Clustering is a dependency-free greedy pass, not scikit-learn
- The similarity threshold is chosen from a labeled evaluation, not guessed
- A cluster's representative is its longest member
- FAQ generation recomputes on every request; nothing is cached or stored

## Phase 4 — Stabilization, Optimization and Documentation

Scoped to hardening real rough edges found by reading the code, not a
performance pass or a deployment change: the application stays local and
single-user. Found by auditing each endpoint's error handling and the upload
duplicate-protection path against what the codebase already documents about
itself, rather than from a bug report.

### Completed (2026-08-16)

- [x] `ingestion_pipeline.recover_interrupted_jobs` — fails any job still
      `UPLOADED` or `PROCESSING` at startup, since a background task cannot
      survive the process that ran it exiting
- [x] `scripts/recover_interrupted_jobs.py` — runs it as its own step in the
      `backend` service's Docker Compose command, between `alembic upgrade
      head` and `uvicorn`; deliberately not wired into FastAPI's `lifespan`
- [x] `EmbeddingError` now returns `503` from `/retrieval/compare`,
      `/retrieval/answer`, `/quizzes/generate` and `/faq/generate`, matching
      the existing `RerankerError`/`LLMError` handling
- [x] `/quizzes/generate` now catches retrieval failures from
      `MCQGenerator.plan()`, not only from `generate()`
- [x] A race between two uploads of the same brand-new file — both passing
      the duplicate check before either commits — is caught as an
      `IntegrityError` and resolved as an ordinary reuse, instead of an
      unhandled `500`
- [x] 14 new backend tests, all against the real database or the real HTTP
      layer — no new frontend surface, so no new frontend tests

### Verified end to end

- A document manually set to `PROCESSING` (simulating a crash) is untouched by
  re-upload until `recover_interrupted_jobs` runs, then re-upload retries it
  in place — the exact failure chain the fix targets, exercised start to
  finish in one test rather than asserted in pieces
- `uv run python -m examrag.scripts.recover_interrupted_jobs` run against the
  live `docker compose` database: connects, finds nothing stuck, exits cleanly
- Full suite: `make check` — 348 backend tests, 44 frontend tests, `ruff
  format --check`, `ruff check`, `mypy`, `tsc --noEmit` all clean

### Problems

- None new. The four fixes above were each found by reading a call site next
  to its siblings (e.g. every other retrieval-backed endpoint already caught
  `RerankerError`) rather than by something breaking during this phase.

### Decisions

Recorded in [decisions.md](decisions.md):

- Crash recovery runs alongside migrations, not in FastAPI's lifespan
- Re-uploading a document stuck at PROCESSING did nothing; recovery is what fixes it
- `EmbeddingError` gets the same 503 treatment as `RerankerError` and `LLMError`
- A raced duplicate upload is caught as an `IntegrityError`, not prevented
