# Retake

> QA and surgical regeneration for AI-narrated audiobooks.

Retake generates narration with ElevenLabs, checks the audio against the manuscript, flags dropped words, repetitions, silences and truncations on a waveform, and regenerates only the affected sentence — with a credit ledger that shows what each fix cost and what it saved.

**Status:** week 0 — scaffold. See [docs/ROADMAP.md](docs/ROADMAP.md).

<!-- Week 10: GIF + live demo link here -->

## Why

Long-form AI narration is ~90 % right on the first pass; the remaining 10 % is found by listening to everything and fixed by regenerating — which costs credits every time. Retake makes that loop visible, targeted and cheap. Background: [docs/PROJECT.md](docs/PROJECT.md).

## Architecture

FastAPI + arq worker + PostgreSQL + Redis + object storage on the backend, React/TypeScript on the front. One image, two processes. Details and diagram: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Decisions: [docs/adr/](docs/adr/).

## Run locally

```bash
cp .env.example .env        # add your ElevenLabs key
make dev                    # docker compose up
open http://localhost:5173  # web
open http://localhost:8000/docs  # API
```

## Quality

`make test` · `make lint` · CI on every PR (ruff, mypy strict, pytest with real Postgres/Redis, eslint, tsc, vitest). Measured results: [docs/METRICS.md](docs/METRICS.md).

## Learning project

This repository doubles as a documented learning journey from TypeScript to Python backend engineering: [docs/learning-log/](docs/learning-log/). Built with Claude Code under a [learning contract](CLAUDE.md).

## Known limits

TXT/Markdown only · single narrator · pronunciation is not scored automatically · no Studio API.

## License

MIT
