"""FastAPI dependencies. One AsyncSession per request; closed when the handler returns."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from retake.db.session import SessionFactory


# TODO(task 5): add a test that a handler raising mid-request leaves nothing committed
# (the `async with` below must roll back). Needs the first real router to exercise it.
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:  # __aexit__ rolls back anything uncommitted
        yield session


# Usage in a router: `async def handler(session: SessionDep) -> ...`
SessionDep = Annotated[AsyncSession, Depends(get_session)]
