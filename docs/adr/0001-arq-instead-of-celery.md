# 0001: Use arq instead of Celery for background jobs

## Status
Proposed — the developer decides after reading both docs (week 1)

## Context and problem
Generating and analysing audio outlives an HTTP request. We need retries, job state, concurrency limits and progress events. The stack is async (FastAPI, SQLAlchemy async, httpx). Redis is already required.

## Decision drivers
- Native asyncio so the httpx adapter and DB sessions can be reused
- Small operational footprint for a solo project
- Transparent enough to be explained in an interview
- Retries and idempotency support

## Considered options
- FastAPI BackgroundTasks: runs in the API process; no retries, lost on restart. Too weak.
- arq: async-first, Redis-backed, small codebase, retries and cron. Smaller ecosystem.
- Celery: industry standard, huge ecosystem, but sync-first; async work needs workarounds; more moving parts.
- Managed workflow (Temporal, etc.): overkill.

## Decision
(To be filled in by the developer.)

## Consequences
- Good: worker and API are separate processes from one image.
- Bad: progress persistence and cancellation are our responsibility.

## Confirmation
- Worker integration test with real Redis: retry after a transient failure, no double ledger entry on duplicate delivery.

## Interview explanation
(To be filled in after the decision.)
