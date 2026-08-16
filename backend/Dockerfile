FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install dependencies first so code changes do not invalidate this layer.
# Runtime only: the test tooling and the tests themselves are not shipped, and
# the suite runs on the host with `make test`.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uvicorn", "examrag.main:app", "--host", "0.0.0.0", "--port", "8000"]
