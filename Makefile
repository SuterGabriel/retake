.PHONY: dev down test lint migrate api-test web-test

dev:
	docker compose up --build

down:
	docker compose down

test: api-test web-test

api-test:
	cd apps/api && uv run alembic upgrade head && uv run pytest

web-test:
	cd apps/web && npm test -- --run

lint:
	cd apps/api && uv run ruff format --check . && uv run ruff check . && uv run mypy src
	cd apps/web && npm run lint && npm run typecheck

migrate:
	cd apps/api && uv run alembic upgrade head
