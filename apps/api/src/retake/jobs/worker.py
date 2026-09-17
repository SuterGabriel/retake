"""arq worker settings. Real job functions are registered here from week 3 on.

arq refuses to start without at least one function, so `ping` is a placeholder
that also serves as a smoke test for the queue (`await pool.enqueue_job("ping")`).
"""

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from retake.config import get_settings


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Callable[..., Awaitable[Any]]]] = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().generation_concurrency
