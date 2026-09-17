"""Engine (one per process) and session factory (one session per request or job).

The factory is shared; a session never is. See docs/learning-log/python-for-ts-devs.md.
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from retake.config import get_settings


def create_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        # One connection per concurrent job or request. Settings validate that
        # DATABASE_POOL_SIZE >= GENERATION_CONCURRENCY.
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_size,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: after commit, attributes stay loaded instead of triggering a
    # lazy reload, which would be an implicit await and fails in async code.
    return async_sessionmaker(engine, expire_on_commit=False)


# Process-wide singletons for the API process. Jobs build their own in week 3 (on_startup).
engine = create_engine()
SessionFactory = create_session_factory(engine)
