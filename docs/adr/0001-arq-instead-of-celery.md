# 0001: Use arq instead of Celery for background jobs

## Status
Accepted (2026-09-17)

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
We choose **arq**. The deciding reason is not throughput but reuse: every service, the
httpx adapter and the async session factory are `async def` because the API needs them that
way. An arq job is an `async def` that awaits the same `ProjectService`/`LedgerService` the
routers use, on the same engine. With Celery each task would need `asyncio.run(...)` (a new
event loop per job, incompatible with a loop-bound asyncpg pool) or a second, synchronous
data layer. Two code paths for one use case is the cost we refuse.

Celery would be the right call if jobs were CPU-bound (prefork beats an event loop there)
or if Celery infrastructure and experience already existed. Neither applies: the one
heavy job, ffmpeg export, runs as a subprocess started from the loop
(`asyncio.create_subprocess_exec`), and the project starts from zero.

## Consequences
- Good: worker and API are separate processes from one image, sharing one service layer.
- Good: `GENERATION_CONCURRENCY` is `max_jobs` on one event loop; rate limiting is one number.
- Bad: progress persistence and cancellation are our responsibility.
- Bad: small ecosystem, no Flower-style dashboard; job state is inspected via Redis or our own
  `GET /projects/{id}/segments` and SSE events.
- Watch: a future CPU-bound job must use `asyncio.to_thread` or a process pool inside the job,
  never block the loop.

## Confirmation
- Worker integration test with real Redis: retry after a transient failure, no double ledger entry on duplicate delivery.

## Interview explanation
The whole stack is async, so I picked a queue that runs jobs as coroutines: the worker calls
the same service classes and database layer as the API, one code path instead of two. Celery
is the standard, but it is sync-first and would have forced either an event loop per task or
a second synchronous data layer. If a job ever becomes CPU-bound I move that work to a thread
or process from inside the job rather than switching queues.
