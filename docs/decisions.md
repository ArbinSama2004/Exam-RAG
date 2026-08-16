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

---

## The embedding model is a constant, validated at load

**Decision:** `EMBEDDING_MODEL_NAME` is a module constant, and the model's
vector width is checked against `EMBEDDING_DIMENSIONS` when it loads.

**Reason:** The model and the column width are one decision, not two. A model
name in the environment would let someone point at a 768-dimensional model and
discover the mismatch as an opaque insert failure at ingestion time, after
conversion and chunking have already run. Keeping it in code means the pairing
is reviewable, and the load-time check turns any future mismatch into a message
that names the problem. `embedding_model` is still recorded per document, which
is what makes a model change detectable in stored data.

**Date:** 2026-08-16

---

## Embedding depends on a protocol, not on SentenceTransformer

**Decision:** `EmbeddingGenerator` accepts any object satisfying an `Encoder`
protocol, defaulting to a lazily constructed `SentenceTransformer`.

**Reason:** Without it, every test touching embeddings would download and load a
90 MB model, turning a two-second suite into a slow one and making it depend on
network access. The protocol names the two methods actually used, so a fake is
trivial. The real model is still exercised, by an opt-in test behind
`EXAMRAG_TEST_REAL_MODEL=1`, so the integration is verified without taxing every
run.

**Date:** 2026-08-16

---

## Torch is installed from the CPU-only wheel index on Linux

**Decision:** `torch` is declared explicitly and sourced from
`https://download.pytorch.org/whl/cpu` for `sys_platform == 'linux'`.

**Reason:** The default Linux wheels bundle CUDA. Measured: the backend image
was 17.7 GB before the change and 3.78 GB after, for an application that runs
embeddings on CPU on a single machine. Torch has to be a direct dependency for
the source override to apply, since it arrives transitively through
sentence-transformers. macOS wheels are already CPU/MPS, so the override is
scoped to Linux and local development is unaffected.

**Date:** 2026-08-16

---

## All chunk writes go through `vector_store`

**Decision:** `database/vector_store.py` is the only module that writes to
`chunks`, and `replace_chunks` replaces a document's chunks as a set rather
than appending.

**Reason:** Three things have to happen together for a document to be correctly
retrievable: its old chunks must go, the new ones must be written, and
`chunk_count`, `embedding_model` and `chunker_version` must be recorded. Split
across callers, a re-ingestion that half-succeeds leaves orphaned chunks that
retrieval still returns, with the document claiming a model that did not
produce them. One function makes that impossible to get wrong.

**Date:** 2026-08-16

---

## A failed upload is retried in place, not duplicated

**Decision:** Re-uploading a file that already exists for the same purpose
returns the existing document untouched, unless its last ingestion failed — in
which case the same document is reset to `UPLOADED`, its file is written again
and a new ingestion job is queued.

**Reason:** The first implementation created a new document row for a failed
re-upload and immediately hit the `(original_file_hash, purpose)` unique
constraint. The constraint is right, so the behaviour had to change. Retrying
in place is also better: the frontend keeps the document id it is already
polling, the failure history stays attached to the document through its jobs,
and rewriting the file recovers a document whose upload volume was cleared.

**Date:** 2026-08-16

---

## Ingestion commits after every stage

**Decision:** `run_ingestion` commits the job's status and stage as each stage
begins, rather than once at the end.

**Reason:** The status endpoint exists so the frontend can show real progress.
Committing only at the end would make every document jump from `UPLOADED`
straight to `READY` or `FAILED`, and the specification's progress display —
converting, chunking, embedding, indexing — would have nothing to show. It also
means a backend that dies mid-run leaves a document visibly stuck in
`PROCESSING` rather than silently lost.

Failures are recorded rather than raised, since a background task has no caller
to raise to. The pipeline rolls back first, so a half-finished run cannot leave
chunks that retrieval would return.

**Date:** 2026-08-16

---

## Ingestion status is polled, and polling continues in the background

**Decision:** `IngestionProgress` polls `GET /documents/{id}/status` every
second, stops as soon as the status is `READY` or `FAILED`, and sets
`refetchIntervalInBackground: true`.

**Reason:** Polling suits a local single-user application — the specification
asks for it, and it needs no WebSocket, no server-sent events and no extra
state on either side. Stopping at a terminal status matters because the
alternative is a page that queries the backend forever after the work is done.

Background polling is not optional here: TanStack Query pauses interval
refetching while the window is unfocused, and this app disables
refetch-on-focus, so a user who switched tabs during a long PDF came back to a
progress list frozen at whatever stage it had reached. That was observed in the
browser, not reasoned about.

**Date:** 2026-08-16

---

## The frontend is tested with Vitest and Testing Library

**Decision:** Add Vitest, Testing Library and jsdom, and test the upload form,
progress polling and document list against a stubbed `fetch`.

**Reason:** With Task 7 the frontend stopped being a placeholder: it decides
when an upload may be submitted, when to stop polling, and how to present
failures. Those are the behaviours a user actually depends on, and none of them
are covered by the backend suite. Testing against a stubbed `fetch` rather than
a running backend keeps the suite fast and makes error paths — a rejected
upload, an unreachable backend, a failed ingestion — easy to reproduce.

Vitest shares Vite's config and transform pipeline, so this adds a test runner
rather than a second build system.

**Date:** 2026-08-16

---

## Fusion combines ranks, not scores

**Decision:** Reciprocal Rank Fusion over the rank each strategy assigned, with
the damping constant `k = 60`.

**Reason:** A cosine similarity of 0.59 and a `ts_rank_cd` of 0.004 — both real
values from the same query on the same corpus — say nothing about each other.
Any attempt to normalise them into a common scale would be an invented
weighting. Ranks are comparable by construction, and summing reciprocal ranks
gives a chunk found by both strategies a higher score than one found by either,
which is precisely the signal hybrid retrieval exists to capture.

**Date:** 2026-08-16

---

## Reranking uses a cross-encoder, not the LLM

**Decision:** `CrossEncoderReranker` wraps `ms-marco-MiniLM-L-6-v2` and runs
over the fused candidates, before context building.

**Reason:** The bi-encoder behind vector search embeds the query and each chunk
separately, so it never compares them directly. A cross-encoder reads the pair
together and scores how well that chunk answers that query — much more accurate,
and far too slow to run over a whole corpus, which is why it runs last over a
few dozen candidates. Asking an LLM instead would be slower, cost more and give
non-deterministic ordering for a job a purpose-built model does better.

Measured on a real query: the cross-encoder scored the relevant passage +4.82
and an off-topic one −9.02, an ordering neither vector nor keyword search
produced on its own.

**Date:** 2026-08-16

---

## MCQ generation separates database work from model calls

**Decision:** `MCQGenerator.plan` performs all retrieval, the endpoint commits,
and `MCQGenerator.generate` then makes only model calls.

**Reason:** The first implementation interleaved them, and the first live run
failed with "the underlying connection is closed" partway through the second
section. A quiz takes tens of seconds to minutes, and holding a database
transaction open across those calls leaves a connection idle long enough to be
dropped. Even without that failure, pinning a connection and an open
transaction while waiting on an external service is the wrong shape.

**Date:** 2026-08-16

---

## Quizzes are stored server-side, and a question is answered once

**Decision:** Generated questions, their correct index and their explanations
live in `quiz_questions`. `POST /quizzes/generate` serialises only id, position,
question and options. A `UNIQUE` constraint on `quiz_answers.question_id` makes
a second answer to the same question impossible.

**Reason:** The specification is explicit that hiding the answer in the frontend
is not sufficient — anything sent to the browser is one devtools panel away.
Grading on the server means the key never leaves it until the user has
committed. The uniqueness constraint closes the remaining hole: without it,
answering repeatedly turns the endpoint into an oracle for the correct option.

Tests assert on the raw response body rather than parsed fields, because a leak
would most likely arrive as an extra key nobody meant to serialise.

**Date:** 2026-08-16

---

## The default model is a cloud model, and the docs say so

**Decision:** `OLLAMA_MODEL` defaults to `gpt-oss:20b-cloud`.

**Reason:** Ollama was chosen for local, offline, no-key generation. On this
machine `llama3.1:8b` ran at 0.4 tokens/second and timed out at 180 s per
section, making the MCQ feature unusable. `gpt-oss:20b-cloud` completes the same
three-section quiz in 43 seconds.

The trade-off is real and is documented rather than glossed: a `-cloud` model is
proxied by Ollama to ollama.com, so prompts — including passages retrieved from
the user's own documents — leave the machine. The README and `.env.example` both
say this and show how to switch to a pulled local model on hardware that can run
one. The `LLMClient` protocol means that switch is a configuration change.

**Date:** 2026-08-16

---

## FAQ extraction relies on the cleaner's structural-line rule, not a new parser

**Decision:** `question_extractor.py` finds questions by matching numbering
markers (`1.`, `Q2`, `(a)`, `b)`) at the start of a line within a chunk's
content, then absorbing following lines until the next marker or a blank line.

**Reason:** `markdown_cleaner._STRUCTURAL_LINE` already treats a numbered line
(`\d+[.)]\s`) the same way it treats a list item: its line break is kept
rather than reflowed into the surrounding prose. That is what makes a
numbered exam question recoverable from stored chunk content without a second
pass over the original PDF or a bespoke past-paper parser — the structure
extraction depends on was preserved for an unrelated reason (protecting list
items) and turns out to protect question numbering too.

This is a heuristic, and an unusually formatted past paper can miss or
malform a question — the same trade-off `pdf_to_markdown`'s heading inference
already makes for the same reason: a PDF carries no explicit structure to
parse, only text that a good heuristic can mostly recover.

**Date:** 2026-08-16

---

## Clustering is a dependency-free greedy pass, not scikit-learn

**Decision:** `question_clusterer.py` assigns each question to the nearest
existing cluster centroid by cosine similarity, using plain numpy, rather than
adding scikit-learn for `AgglomerativeClustering` or `DBSCAN`.

**Reason:** The same reasoning as every other dependency in this project:
added by the task that needs it, not upfront. A single past paper's worth of
questions is tens to a few hundred items — small enough that an O(n·k) greedy
pass against running centroids costs milliseconds, and numpy is already a
direct dependency of embeddings. Reaching for scikit-learn here would need
nothing scikit-learn offers that this doesn't already do at this scale.

The trade-off is real: single-pass greedy clustering is order-dependent and
will occasionally split into two clusters what a global method would merge
into one. That is judged acceptable because clustering quality is measured
directly — see the labeled-set evaluation below — rather than assumed from
the algorithm's reputation.

**Date:** 2026-08-16

---

## The similarity threshold is chosen from a labeled evaluation, not guessed

**Decision:** `DEFAULT_SIMILARITY_THRESHOLD = 0.83`, picked by running the real
embedding model over a hand-labeled set of 15 past-paper-style questions (4
groups of 2–3 paraphrased repeats, 5 unrelated distractors) and choosing the
threshold that scores well on pairwise precision/recall. At 0.83 the labeled
set scores precision 1.00, recall 0.88, F1 0.93.

**Reason:** This is Phase 3's evaluation requirement. A clustering threshold
picked without measurement is just a guess dressed up as a constant, and the
two failure directions have different costs: too low merges genuinely
different questions into one misleading FAQ entry; too high hides real
repeats as unrelated singletons. Measuring against hand labels makes the
trade-off visible instead of assumed, and gives future threshold changes
something concrete to compare against.

The evaluation needs the real model — a fake or hash-based encoder cannot
distinguish a paraphrase from a distractor — so it runs as an opt-in test
(`EXAMRAG_TEST_REAL_MODEL=1 uv run pytest tests/faq/test_clustering_evaluation.py -s`),
the same convention the embedding suite already uses for its own real-model
test.

**Date:** 2026-08-16

---

## A cluster's representative is its longest member

**Decision:** `faq_pipeline._build_cluster` picks the longest normalized
question in a cluster as the representative shown to the user; the rest are
kept as variants.

**Reason:** A shorter member of a genuine duplicate cluster is more often a
paraphrase that dropped a clause, or an extraction that missed a continuation
line, than a meaningfully different question — the longest phrasing is the
best available proxy for the most complete one, without adding a second
embedding comparison (distance to centroid) to pick a "typical" member
instead.

**Date:** 2026-08-16

---

## FAQ generation recomputes on every request; nothing is cached or stored

**Decision:** `POST /faq/generate` runs extraction, embedding and clustering
fresh on every call. No FAQ table, no stored cluster, no invalidation logic.

**Reason:** Nothing in the pipeline is slow enough to justify caching —
extraction is regex over already-loaded chunks, and clustering a paper's worth
of questions is a few hundred dot products. Caching would add a staleness
problem (a newly uploaded past paper not reflected until some invalidation
fires) to solve a performance problem that does not exist yet. This mirrors
`POST /retrieval/compare`: compute-on-read where computing is cheap, store
server-side state only where correctness requires it (quizzes, because the
answer key must not reach the browser early).

**Date:** 2026-08-16

---

## Crash recovery runs alongside migrations, not in FastAPI's lifespan

**Decision:** `recover_interrupted_jobs` — which fails any ingestion job still
`UPLOADED` or `PROCESSING`, since a background task cannot survive the process
that ran it exiting — runs as its own step in the `backend` service's Docker
Compose command, between `alembic upgrade head` and `uvicorn`. It is not
wired into `main.py`'s `lifespan`.

**Reason:** Liveness (`GET /health`) is deliberately dependency-free — that is
the entire reason liveness and readiness are separate endpoints, so the
frontend can show a meaningful message while PostgreSQL is still starting.
Putting a database query in `lifespan` startup would make that guarantee
false: the API could no longer come up before the database does, and every
test that boots the app through its lifespan (several do, to test liveness
itself) would need a reachable database just to construct the client. Running
the sweep as a separate step after `alembic upgrade head`, which already
requires the database, gets the same ordering guarantee — recovery always
completes before the API serves its first request — without threading a
database dependency through application startup.

**Date:** 2026-08-16

---

## Re-uploading a document stuck at PROCESSING did nothing; recovery is what fixes it

**Decision:** On top of the decision above, retry-in-place (`api/upload.py`)
still only fires for a document whose status is `FAILED`. Nothing changed
there. What changed is that `recover_interrupted_jobs` now guarantees a
crash-orphaned document reaches `FAILED`, which is the state retry-in-place
already knew how to handle.

**Reason:** This was Phase 4's most concrete finding: the README always said
"if the backend stops mid-job, that job must be re-uploaded," but re-uploading
did not actually work. `_find_existing` only retries in place when the
existing document's status *is* `FAILED` — a document orphaned by a crash
sits at `PROCESSING` (or `UPLOADED`), which the code's own condition
(`if existing.status is not FAILED: reuse`) sent down the reuse path instead,
returning the same stuck document untouched. The fix is recovery marking it
`FAILED`, not a second code path in the upload handler — the retry logic was
already correct, it just needed a way to run.

**Date:** 2026-08-16

---

## `EmbeddingError` gets the same 503 treatment as `RerankerError` and `LLMError`

**Decision:** `/retrieval/compare`, `/retrieval/answer`, `/quizzes/generate`
and `/faq/generate` each catch `EmbeddingError` and return `503`, matching how
`RerankerError` and `LLMError` were already handled.

**Reason:** All three exceptions mean the same thing — a model this request
needed is not available — and every other one already got a clean, actionable
response instead of a raw traceback. `EmbeddingError` was the one gap: nothing
caught it, so a corrupted model cache or a dimension mismatch surfaced as an
unhandled `500`. Found by reading the four call sites side by side rather than
by a report, since embeddings almost never fail once ingestion has proven the
model loads — which is exactly why the gap went unnoticed.

`/quizzes/generate` needed the fix in two places: `MCQGenerator.plan()`
retrieves before any model call and was outside the endpoint's only
try/except, which wrapped `generate()` alone.

**Date:** 2026-08-16

---

## A raced duplicate upload is caught as an `IntegrityError`, not prevented

**Decision:** `upload_document` does not lock or re-check before inserting a
new document. It attempts the insert, and if the `(original_file_hash,
purpose)` constraint rejects it — because a concurrent request for the same
new file won the race — it rolls back, deletes the file it had already
written, looks the document up again, and returns the winner's row as
`reused: true`.

**Reason:** Locking (`SELECT ... FOR UPDATE`) or a Redis-backed mutex would
prevent the race, but for a local single-user application the race is rare
enough (two near-simultaneous requests for the exact same new file — a
double-click, a retried request) that the constraint itself is a sufficient
guard, and it is one the database already enforces for free. What was missing
was handling the exception it raises: before this, the loser's request ended
in an unhandled `500` instead of the same graceful reuse an intentional
re-upload gets.

**Date:** 2026-08-16
