# Tools and Frameworks

Every major technology used in ExamRAG, explained plainly. Entries are added as
each tool is introduced.

## uv

**What it is:** A fast Python package and project manager.

**Why we use it:** It installs dependencies, creates the virtual environment and
writes `uv.lock`, which records the exact version of every package. Committing
that lock file means anyone who clones the repository gets an identical
environment.

---

## Python 3.12

**What it is:** The Python version the backend targets, pinned in
`backend/.python-version` and `requires-python`.

**Why we use it:** One fixed version keeps local runs, Docker builds and CI
behaving the same way.

---

## FastAPI

**What it is:** A Python framework for building web APIs.

**Why we use it:** The frontend needs an API for uploading documents, generating
MCQs and generating FAQs. FastAPI validates requests and responses using type
hints and generates interactive API documentation at `/docs` automatically.

---

## Uvicorn

**What it is:** The server that runs the FastAPI application.

**Why we use it:** FastAPI is a framework, not a server. Uvicorn is what
actually listens on port 8000 and handles HTTP connections.

---

## Pydantic v2 and pydantic-settings

**What it is:** Pydantic turns type-annotated classes into validated data
models. pydantic-settings is its extension for reading configuration from
environment variables and `.env` files.

**Why we use it:** API request and response shapes are defined once, as
classes, and validated automatically. Configuration gets the same treatment: an
invalid `APP_ENV` fails at startup with a clear message instead of causing odd
behavior later.

---

## PostgreSQL

**What it is:** A relational database.

**Why we use it:** It stores documents, chunks, metadata, ingestion jobs and
quiz sessions. It also provides the full-text search used for the keyword half
of hybrid retrieval.

---

## pgvector

**What it is:** A PostgreSQL extension for storing and searching vectors.

**Why we use it:** RAG represents text as embeddings — long lists of numbers —
and needs to find the ones most similar to a query. pgvector adds a `vector`
column type and similarity search directly in PostgreSQL, so no separate vector
database is needed.

---

## SQLAlchemy 2 (async) and asyncpg

**What it is:** SQLAlchemy maps Python classes to database tables and builds
queries. asyncpg is the async PostgreSQL driver it talks through.

**Why we use it:** FastAPI is asynchronous, so database calls should be too —
otherwise a slow query blocks other requests. SQLAlchemy also keeps the schema
defined in Python, which Alembic reads to generate migrations.

---

## Alembic

**What it is:** A database migration tool for SQLAlchemy.

**Why we use it:** The database schema changes as the project grows. Alembic
records each change as a versioned migration script, so an existing database
can be upgraded with `alembic upgrade head` instead of being recreated.

---

## React, TypeScript and Vite

**What it is:** React builds the user interface, TypeScript adds static types to
JavaScript, and Vite is the development server and build tool.

**Why we use it:** The upload, quiz and FAQ screens are interactive and
stateful, which suits React. TypeScript catches mistakes such as misspelled API
fields before the app runs. Vite gives instant reloads during development.

---

## TanStack Query

**What it is:** A React library for fetching and caching server data.

**Why we use it:** The upload screen needs to poll ingestion status until a
document is `READY`, and every screen needs loading and error states. TanStack
Query provides polling, caching and those states without hand-written
`useEffect` code.

---

## pytest, pytest-asyncio and pytest-cov

**What it is:** The testing framework, its async support, and its coverage
plugin.

**Why we use it:** Most backend code is `async`, and pytest-asyncio lets tests
await it directly. Fixtures make it easy to build an isolated application
instance per test.

---

## httpx

**What it is:** An HTTP client that works synchronously and asynchronously.

**Why we use it:** Tests call the API through it in-process — no server needs to
be running. It is also the client the backend will use to call the LLM provider.

---

## Ruff

**What it is:** A fast Python linter and formatter.

**Why we use it:** It replaces several separate tools (formatting, unused
imports, import sorting, common bug patterns) with one, so style stays
consistent without discussion.

---

## mypy

**What it is:** A static type checker for Python.

**Why we use it:** It verifies the type hints are actually correct, catching
mistakes such as passing `None` where a string is required before the code runs.

---

## Docker and Docker Compose

**What it is:** Docker packages each service into a container. Compose starts
them together from one file.

**Why we use it:** `make up` starts PostgreSQL with pgvector, the backend and
the frontend with matching configuration. Nobody has to install PostgreSQL by
hand. Named volumes keep the database and uploaded files across restarts.

---

## Make

**What it is:** A command runner.

**Why we use it:** It hides long commands behind short ones — `make up`,
`make test`, `make check` — so the README does not have to teach Docker and uv
syntax.
