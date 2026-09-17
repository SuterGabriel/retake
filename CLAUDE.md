# Retake

QA and surgical regeneration for AI-narrated audiobooks. Generates narration
with ElevenLabs, checks the audio against the manuscript, flags omissions and
artifacts, and regenerates only the affected sentence, with a credit ledger.

This is a **learning project**: the developer is a strong Angular/TypeScript
frontend engineer learning Python backend engineering. Correctness,
explainability and documented trade-offs beat speed. Read `docs/PROJECT.md`
and `docs/ROADMAP.md` before starting any task.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, arq + Redis, PostgreSQL
- Frontend: React 19, TypeScript, Next.js (App Router), TanStack Query, wavesurfer.js
- Tooling: uv, ruff, mypy (strict), pytest, vitest, Docker Compose, GitHub Actions

## Commands
- `make dev` – start everything (compose)
- `make test` – backend + frontend tests
- `make lint` – ruff, mypy, eslint, tsc
- `make migrate` – alembic upgrade head
- Backend only: `cd apps/api && uv run pytest` / `uv run ruff check .` / `uv run mypy src`
- Frontend only: `cd apps/web && npm test` / `npm run lint`

## Hard rules
1. The ElevenLabs API key never reaches the browser, a commit, or a log line.
2. Every ElevenLabs call goes through `integrations/elevenlabs/` and writes a `LedgerEntry`. No exceptions.
3. `domain/` has no imports from FastAPI, SQLAlchemy, arq or httpx. Pure functions only.
4. Route handlers validate and delegate to services; no business logic in routers.
5. A new DB field ships with its Alembic migration in the same commit.
6. Tests never call paid APIs. External calls are mocked with `respx`; opt-in real calls use the `external` marker.
7. Credits are integers, never floats.

## Learning contract
- Before any non-trivial change: explain the approach in 3–5 sentences, name the Python concepts involved and their TypeScript equivalent, then wait for approval.
- For architectural choices present two options with trade-offs and let the developer decide; write the outcome as an ADR (`/adr`).
- After implementing: list what could fail at runtime and which test covers it.
- Prefer readable over clever. No metaprogramming, no unexplained magic.
- Never claim a command passed unless you ran it. Never weaken a test, type check or lint rule silently.
- TDD for `domain/` and `services/ledger.py`: failing test first, developer reads it, then implement.

## Definition of done
Acceptance criteria met · tests green · lint and types green · migration included if schema changed · ADR if architecture changed · summary of what changed and why.
