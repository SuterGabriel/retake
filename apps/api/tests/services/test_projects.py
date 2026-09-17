"""ProjectService: the use cases behind POST /projects and POST /projects/{id}/import.

The service owns the transaction: import is "load project + create segments", all or nothing.
Runs on the rolled-back test session from conftest.py.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from retake.config import get_settings
from retake.db.models import Project, Segment
from retake.services.errors import NothingToImport, ProjectAlreadyImported, ProjectNotFound
from retake.services.projects import ProjectService

CHAPTER = "First one. First two.\n\nSecond one."


async def _segment_count(session: AsyncSession, project_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Segment).where(Segment.project_id == project_id)
    )
    return count or 0


# ---------------------------------------------------------------- create


async def test_create_persists_project_with_defaults_from_settings(session: AsyncSession) -> None:
    service = ProjectService(session)

    project = await service.create(title="Chapter 1")

    stored = await session.get(Project, project.id)
    assert stored is not None
    assert stored.title == "Chapter 1"
    assert stored.voice_id == get_settings().elevenlabs_default_voice_id
    assert stored.model_id == get_settings().elevenlabs_default_model_id
    assert stored.voice_settings == {}
    assert stored.created_at.tzinfo is not None  # timezone-aware, never naive


async def test_create_uses_explicit_voice_model_and_settings(session: AsyncSession) -> None:
    service = ProjectService(session)

    project = await service.create(
        title="Chapter 1",
        voice_id="voice-x",
        model_id="model-y",
        voice_settings={"stability": 0.4},
    )

    assert (project.voice_id, project.model_id) == ("voice-x", "model-y")
    assert project.voice_settings == {"stability": 0.4}


# ---------------------------------------------------------------- import_text


async def test_import_creates_segments_in_order_with_paragraphs(session: AsyncSession) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")

    segments = await service.import_text(project.id, CHAPTER)

    assert [(s.position, s.paragraph_index, s.text) for s in segments] == [
        (0, 0, "First one."),
        (1, 0, "First two."),
        (2, 1, "Second one."),
    ]
    assert all(s.project_id == project.id for s in segments)
    assert all(s.version == 1 for s in segments)
    # Normalisation (numbers to words, case folding, ...) arrives in week 4; until then the
    # normalised text is the text itself, never empty.
    assert all(s.normalized_text == s.text for s in segments)


async def test_import_is_persisted(session: AsyncSession) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")

    await service.import_text(project.id, CHAPTER)

    assert await _segment_count(session, project.id) == 3


async def test_import_unknown_project_raises_not_found(session: AsyncSession) -> None:
    service = ProjectService(session)

    with pytest.raises(ProjectNotFound):
        await service.import_text(uuid.uuid4(), CHAPTER)


async def test_second_import_is_rejected_and_changes_nothing(session: AsyncSession) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")
    await service.import_text(project.id, CHAPTER)

    with pytest.raises(ProjectAlreadyImported):
        await service.import_text(project.id, "Another. Text.")

    assert await _segment_count(session, project.id) == 3


async def test_import_with_no_sentences_raises_and_leaves_project_importable(
    session: AsyncSession,
) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")

    with pytest.raises(NothingToImport):
        await service.import_text(project.id, "// only a comment\n\n   ")

    assert await _segment_count(session, project.id) == 0
    assert len(await service.import_text(project.id, CHAPTER)) == 3


# ---------------------------------------------------------------- IntegrityError narrowing


def _integrity_error(message: str) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, Exception(message))


async def test_unique_position_violation_on_commit_is_reported_as_conflict(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")

    async def commit_raises() -> None:
        raise _integrity_error('duplicate key violates "uq_segments_project_id_position"')

    monkeypatch.setattr(session, "commit", commit_raises)

    with pytest.raises(ProjectAlreadyImported):
        await service.import_text(project.id, CHAPTER)


async def test_other_integrity_errors_on_commit_propagate(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ProjectService(session)
    project = await service.create(title="Chapter 1")

    async def commit_raises() -> None:
        raise _integrity_error('violates check constraint "ck_segments_position_nonnegative"')

    monkeypatch.setattr(session, "commit", commit_raises)

    with pytest.raises(IntegrityError):
        await service.import_text(project.id, CHAPTER)
