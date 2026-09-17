"""ProjectService: create a project, import a chapter into segments."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from retake.config import get_settings
from retake.db.models import Project, Segment
from retake.domain.segmentation import split
from retake.services.errors import NothingToImport, ProjectAlreadyImported, ProjectNotFound

SEGMENT_POSITION_UNIQUE = "uq_segments_project_id_position"  # name from db/models.py


def _violates(exc: IntegrityError, constraint_name: str) -> bool:
    """True if the database error names this constraint (asyncpg puts it in the message)."""
    return constraint_name in str(exc.orig)


class ProjectService:
    """One instance per request or job; it holds that unit of work's session.

    Import is once-only by design. A client that times out after a successful import and
    retries gets 409; the follow-up `GET /projects/{id}/segments` (week 5) is the way to
    recover the result.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        title: str,
        voice_id: str | None = None,
        model_id: str | None = None,
        voice_settings: dict[str, Any] | None = None,
    ) -> Project:
        settings = get_settings()
        project = Project(
            title=title,
            voice_id=voice_id or settings.elevenlabs_default_voice_id,
            model_id=model_id or settings.elevenlabs_default_model_id,
            voice_settings=voice_settings if voice_settings is not None else {},
        )
        self._session.add(project)
        await self._session.commit()
        return project

    async def import_text(self, project_id: uuid.UUID, text: str) -> list[Segment]:
        """Split `text` into sentences and store them as the project's segments.

        All or nothing: either every segment is committed or none is. A project can be
        imported once; re-import with segment versioning is a later use case.
        """
        project = await self._session.get(Project, project_id)
        if project is None:
            raise ProjectNotFound(f"Project {project_id} not found")
        if await self._segment_count(project_id) > 0:
            raise ProjectAlreadyImported(f"Project {project_id} already has segments")

        drafts = split(text)
        if not drafts:
            raise NothingToImport("The text contains no sentences")

        segments = [
            Segment(
                project_id=project_id,
                position=draft.position,
                paragraph_index=draft.paragraph_index,
                text=draft.text,
                # domain.normalize arrives in week 4; until then the text is its own normal form.
                normalized_text=draft.text,
            )
            for draft in drafts
        ]
        self._session.add_all(segments)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _violates(exc, SEGMENT_POSITION_UNIQUE):
                # Two concurrent imports both saw zero segments; the unique constraint
                # rejected the second one. Report it as the conflict it is.
                raise ProjectAlreadyImported(f"Project {project_id} already has segments") from exc
            raise  # anything else (FK, CHECK) is a bug, not a conflict
        return segments

    async def _segment_count(self, project_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count()).select_from(Segment).where(Segment.project_id == project_id)
        )
        return count or 0
