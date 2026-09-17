# Architecture

## Overview

```mermaid
flowchart LR
  B[Browser<br/>React + TS (Next.js)] -- REST / SSE --> A[FastAPI]
  A --> P[(PostgreSQL)]
  A --> Q[(Redis<br/>arq queue)]
  W[arq worker] --> Q
  W --> P
  W --> S[(Object store<br/>MinIO / S3)]
  W --> E[ElevenLabs<br/>TTS + Scribe]
  A --> S
```

Modular monolith: one Python package, two processes (API and worker) from the same image. No microservices.

## Backend package layout

```
apps/api/src/retake/
├── domain/          pure functions & dataclasses: segmentation, normalisation, diff, findings, cost, retake planning
├── services/        use cases: ProjectService, GenerationService, AnalysisService, LedgerService, ExportService
├── integrations/
│   └── elevenlabs/  typed httpx adapter (tts.py, scribe.py, client.py, errors.py)
├── jobs/            arq entry points (thin) + worker settings
├── api/             FastAPI routers, schemas (Pydantic), dependencies, SSE
├── db/              SQLAlchemy models, session factory, alembic env
└── config.py        pydantic-settings
```

Dependency direction: `api` → `services` → `domain`; `services` → `integrations`/`db`. `domain` imports nothing from the outer layers.

## Data model

| Table | Key fields |
|---|---|
| `projects` | id, title, voice_id, model_id, voice_settings (json), created_at |
| `segments` | id, project_id, position, paragraph_index, text, normalized_text, version |
| `takes` | id, segment_id, segment_version, attempt, audio_key, duration_ms, status (pending/generating/done/failed), credits (cache; ledger is the source of truth), is_active, created_at |
| `findings` | id, take_id, type, start_ms, end_ms, confidence, details (json), status (open/fixed/ignored) |
| `ledger_entries` | id, project_id, take_id (nullable), kind (tts/stt/retry-skipped), credits (int), idempotency_key (unique), created_at |

Invariants: exactly one active take per segment once any take is done; `ledger_entries.idempotency_key` = `f"{kind}:{segment_id}:{segment_version}:{attempt}"`.
In the database: partial unique index `ux_takes_one_active` (at most one), CHECK `active_requires_done` (only a finished take), UNIQUE `idempotency_key`; "at least one active once any is done" is enforced by the service. Enums are text + CHECK, ids uuid4 (ADR-0003).

## Pipeline

1. **Import** → `domain.segmentation.split(text) -> list[SegmentDraft]`
2. **Generate** → for each segment enqueue `generate_take(segment_id, version)`; worker calls TTS adapter, stores audio, writes Take + LedgerEntry, then enqueues `analyze_take(take_id)`.
3. **Analyze** → Scribe transcript → `domain.normalize` both sides → `domain.diff.align(expected, actual)` → `domain.findings.from_alignment(...)` + `domain.audio_checks` (silence, truncation) → persist Findings.
4. **Retake** → new segment version? No: same text, new Take with `attempt+1`; analyse again; user activates.
5. **Export** → ffmpeg concat of active takes with crossfade + loudnorm → MP3 to object store → download URL.

Progress events (`segment.generating`, `take.done`, `finding.created`, `export.done`) are published to Redis and streamed to the browser over SSE.

## API surface (v1)

```
POST   /projects
POST   /projects/{id}/import
POST   /projects/{id}/generate
GET    /projects/{id}/segments
GET    /projects/{id}/findings?status=open
POST   /segments/{id}/retake
POST   /takes/{id}/activate
PATCH  /findings/{id}
GET    /projects/{id}/ledger
POST   /projects/{id}/export
GET    /projects/{id}/events        (SSE)
GET    /takes/{id}/audio            (signed/proxied)
```

## Frontend layout

```
apps/web/
├── app/                  Next.js App Router: layout.tsx, page.tsx, projects/[id]/review/page.tsx …
│                         (review page is a Client Component; no route.ts, no Server Actions)
├── features/project/     import, project list
├── features/review/      split view, findings list, waveform, shortcuts, cost bar
├── features/export/
├── components/           generic UI
├── api/                  generated client from OpenAPI
└── lib/                  pure TS helpers (keyboard map, formatting)
```

FastAPI is the only API. Next.js provides routing, layouts and the production server; see ADR-0002.

## Cross-cutting

- Config via `pydantic-settings`; all secrets from env.
- Logging via `structlog` (JSON in prod).
- Credits are `int`. Costs are computed in `domain.cost` from billed characters; the ElevenLabs response headers/fields are the source of truth when available (verify: see `docs/ELEVENLABS.md`).
- Budget check in `LedgerService.reserve()` before enqueueing generation.

## Decisions requiring an ADR (see docs/adr/)
0001 arq vs Celery · 0002 Next.js over Vite · 0003 text enums and uuid ids · 0004 SSE vs WebSockets · 0005 object storage vs DB blobs · 0006 sentence-level segmentation granularity · 0007 deployment platform
