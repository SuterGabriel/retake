"""FastAPI dependencies. One AsyncSession per request; closed when the handler returns.

Routers receive services, never the session: the service is the unit of work and decides
where the transaction ends. Verified by the rollback test in tests/api/test_projects.py.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from retake.db.session import SessionFactory
from retake.services.projects import ProjectService


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:  # __aexit__ rolls back anything uncommitted
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
