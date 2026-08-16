FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.18 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install dependencies first so code changes do not invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --extra dev --frozen --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY tests ./tests
RUN uv sync --extra dev --frozen

EXPOSE 8000

CMD ["uvicorn", "examrag.main:app", "--host", "0.0.0.0", "--port", "8000"]
