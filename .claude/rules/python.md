---
paths:
  - "apps/api/**/*.py"
---

# Python backend rules

- Python 3.12 syntax; type hints on every public function. `mypy --strict` must pass.
- Pydantic models for API schemas, dataclasses for domain objects, SQLAlchemy models for persistence. Never one class for all three.
- Async only where there is I/O. Domain logic stays synchronous.
- Never share one `AsyncSession` across concurrent tasks. Session lifetime = one request or one job.
- No mutable default arguments. No bare `except Exception` unless re-raising with context.
- `datetime.now(tz=UTC)` always; naive datetimes are a bug.
- arq job functions are thin: load the service from `ctx`, call it, return. Logic lives in services.
- Every job must be idempotent (idempotency key = segment id + segment version) or document why not.
- External HTTP via `httpx.AsyncClient` with explicit timeouts, retry with backoff on 429/5xx, honour `Retry-After`.
- Log with `structlog`; never log request bodies containing manuscripts or API keys.
