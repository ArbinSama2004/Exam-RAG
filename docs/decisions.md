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

## Embeddings are a column on `chunks`, not a separate table

**Decision:** Store the vector as `chunks.embedding vector(384)` rather than in
a `chunk_embeddings` table.

**Reason:** The application stores exactly one vector per chunk with one model
at a time, so a separate table would add a join to every retrieval query
without modelling anything the schema does not already express. Keeping the
vector beside the text and its metadata lets vector search, keyword search and
context building read a single row. If multiple embedding models ever need to
coexist, the vector moves to its own table then — that is a migration, not a
redesign of the retrieval layer.

**Date:** 2026-08-16

---

## `content_tsv` is a database-generated column

**Decision:** `chunks.content_tsv` is
`GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`, with a GIN
index, rather than a value the application writes.

**Reason:** Keyword search cannot drift from the text it indexes — PostgreSQL
recomputes the vector on every insert and update, so there is no path where an
edited chunk keeps a stale search vector. It also keeps the ingestion code
free of indexing concerns.

**Date:** 2026-08-16

---

## Embedding dimensionality is a code constant, not a setting

**Decision:** `EMBEDDING_DIMENSIONS = 384` lives in `database/models.py` and is
mirrored in migration `0002`, instead of being read from the environment.

**Reason:** The column type is fixed in the database. Changing the number means
a migration plus re-embedding every stored chunk, so exposing it as an
environment variable would suggest a flexibility that does not exist and would
let a mismatched value fail at query time instead of at review time. The
`embedding_model` recorded per document is what makes a model change
detectable.

**Date:** 2026-08-16

---

## Documents are unique per `(original_file_hash, purpose)`

**Decision:** The uniqueness constraint covers the file hash together with the
document purpose, not the hash alone.

**Reason:** The specification requires that re-uploading an unchanged file does
not trigger redundant embedding generation, and this constraint enforces that
for the case that matters. Including `purpose` still allows the same file to be
registered as both study material and a past paper, which the hash-only
constraint would block — a real scenario, since the two purposes feed different
pipelines.

**Date:** 2026-08-16

---

## Dependencies are added when the feature that uses them lands

**Decision:** Each dependency is added by the task that first uses it, not
upfront. So far: FastAPI, Uvicorn, Pydantic v2, pydantic-settings, SQLAlchemy
(async), asyncpg and Alembic (Task 1); pgvector (Task 2); PyMuPDF and
python-docx (Task 3). Development tooling is pytest, pytest-asyncio,
pytest-cov, httpx, Ruff and mypy.

**Reason:** The full stack is decided upfront, but installing
sentence-transformers, NumPy and scikit-learn before their features exist slows
every install and Docker build and makes it unclear which dependencies are
actually in use. They arrive with the tasks that need them.

**Date:** 2026-08-16

---

## Markdown is the normalized representation, with page numbers preserved

**Decision:** Every supported format is converted to a `LoadedDocument` holding
ordered `DocumentPage` values, each with Markdown and an optional page number,
rather than to one flat string.

**Reason:** The specification requires that generated answers be traceable to
their source, which means chunks need page numbers. Conversion is the last
point at which the source layout is known — once pages are concatenated, the
information is gone and cannot be recovered. Formats without pagination use
`number = None` instead of a fabricated value, so downstream code never mistakes
an invented page for a real one.

**Date:** 2026-08-16

---

## Headings are inferred for PDF and read directly for DOCX

**Decision:** `pdf_to_markdown` derives heading levels from font size relative
to the document's body text (plus short fully-bold lines), while
`docx_to_markdown` maps the paragraph styles the file already carries.

**Reason:** The two formats genuinely differ. DOCX names its structure, so
inferring anything there would be worse than reading it. A PDF carries only
positioned text with font metrics, and headings are needed — Phase 2 must
distribute "all topics" MCQ generation across document sections, which requires
knowing where sections begin. The body size is estimated as the most common
size weighted by character count, so a document that opens with a large title
does not mistake the title for body text.

The heuristic is a heuristic: an unusually styled PDF may produce imperfect
levels. Because chunking consumes headings as metadata rather than as control
flow, a wrong level degrades attribution quality without breaking ingestion.

**Date:** 2026-08-16

---

## Chunking is structure-aware, not a fixed window

**Decision:** `chunker.py` splits on document structure — a heading starts a new
chunk, and the heading path is recorded on every chunk beneath it — rather than
sliding a fixed character window over the text.

**Reason:** Two later requirements depend on it. Retrieved chunks must be
traceable to a source, and a heading breadcrumb plus page number says where a
passage came from far better than an offset. And Phase 2 must distribute
"all topics" MCQ generation across document sections rather than generating
every question from one global top-k context, which requires knowing where
sections begin. A fixed window would have to reconstruct that later from text
that no longer contains it.

Chunks still carry a size target and a sentence-aligned overlap, so structure
determines the boundaries while size keeps them retrievable.

**Date:** 2026-08-16

---

## Chunk sizing lives in code, tied to the chunker version

**Decision:** `TARGET_CHUNK_CHARS`, `MAX_CHUNK_CHARS`, `MIN_CHUNK_CHARS` and
`OVERLAP_CHARS` are constants in `chunker.py`, not environment variables, and
`CHUNKER_VERSION` covers them.

**Reason:** Same reasoning as the embedding dimensionality. These values are
baked into every stored chunk; changing one makes existing chunks inconsistent
with new ones, and the fix is re-ingestion, not a restart. `chunker_version` is
stored per document precisely so that mismatch is detectable, which only works
if the version changes when the values do. Retrieval *tuning* parameters are
different — those are read at query time, affect nothing stored, and Phase 2
exposes them as environment variables as the specification requires.

**Date:** 2026-08-16

---

## Reflowing wrapped prose is the cleaner's job, not the converter's

**Decision:** `pdf_to_markdown` joins the lines of a paragraph with newlines,
preserving the source line breaks. `markdown_cleaner` then rejoins hyphenated
words and reflows the paragraph into continuous prose.

**Reason:** The first implementation had the converter join lines with spaces,
which read correctly but destroyed the information the cleaner needs: a word
split as `phys-\nical` can only be rejoined while the newline is still there,
and a page number is only recognisable as an artefact while it is still on its
own line. The end-to-end composition test caught this — both unit test suites
passed while the combination silently produced `phys- ical` and embedded page
numbers as content.

Keeping extraction and normalization in separate stages also matches the module
boundaries: the converter reports what the PDF contains, the cleaner decides
what is worth keeping.

**Date:** 2026-08-16
