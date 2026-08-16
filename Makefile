.PHONY: setup up down logs migrate test format lint typecheck check run-backend run-frontend clean

setup:
	@test -f .env || cp .env.example .env
	cd backend && uv sync --extra dev
	cd frontend && npm install

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec backend alembic upgrade head

test:
	cd backend && uv run pytest

format:
	cd backend && uv run ruff format .

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

typecheck:
	cd backend && uv run mypy

check: lint typecheck test

run-backend:
	cd backend && uv run uvicorn examrag.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev

clean:
	docker compose down -v
