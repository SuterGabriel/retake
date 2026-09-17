"""Shared test fixtures.

The API key is the only setting without a default. Tests must never need a real
one, so we inject a placeholder before the app module is imported.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

os.environ.setdefault("ELEVENLABS_API_KEY", "test-not-a-real-key")
os.environ.setdefault("ENVIRONMENT", "test")

from retake.api.dependencies import get_session  # must come after the env setup above
from retake.api.main import app
from retake.config import get_settings


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """One connection, one outer transaction, rolled back at the end.

    `join_transaction_mode="create_savepoint"` turns every commit() or rollback() inside the
    test into a SAVEPOINT operation, so a test can provoke an IntegrityError and keep going,
    and a service may commit() without anything reaching the database for good.
    See docs/learning-log/python-for-ts-devs.md, "The savepoint pattern".
    """
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as s:
            yield s
        await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process HTTP client whose requests run on the test's rolled-back session.

    `app.dependency_overrides` swaps `get_session` for the fixture above, so the router,
    the service and the test all see the same transaction. The override is removed after
    the test so other tests get the real dependency.
    """

    async def _test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _test_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)  # only ours, not every override
