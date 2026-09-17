"""The invariants from docs/ARCHITECTURE.md must hold in the database, not only in code.

Runs against the real Postgres (compose or CI service) with the schema at `alembic head`.
Every test runs inside a transaction that is rolled back, so no state is left behind.
"""

import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from retake.db.models import LedgerEntry, LedgerKind, Project, Segment, Take, TakeStatus

# The `session` fixture (savepoint per test) lives in tests/conftest.py.


def _project() -> Project:
    return Project(title="Test chapter", voice_id="voice", model_id="eleven_multilingual_v2")


def _segment(project: Project, position: int = 0) -> Segment:
    return Segment(
        project=project,
        position=position,
        paragraph_index=0,
        text="A sentence.",
        normalized_text="a sentence",
    )


def _take(segment: Segment, *, attempt: int, status: TakeStatus, active: bool) -> Take:
    return Take(
        segment=segment, segment_version=1, attempt=attempt, status=status, is_active=active
    )


async def test_ledger_rejects_duplicate_idempotency_key(session: AsyncSession) -> None:
    project = _project()
    key = f"tts:{uuid.uuid4()}:1:1"
    session.add_all(
        [
            LedgerEntry(project=project, kind=LedgerKind.TTS, credits=12, idempotency_key=key),
            LedgerEntry(project=project, kind=LedgerKind.TTS, credits=12, idempotency_key=key),
        ]
    )

    with pytest.raises(IntegrityError, match="uq_ledger_entries_idempotency_key"):
        await session.flush()


async def test_at_most_one_active_take_per_segment(session: AsyncSession) -> None:
    segment = _segment(_project())
    session.add_all(
        [
            _take(segment, attempt=1, status=TakeStatus.DONE, active=True),
            _take(segment, attempt=2, status=TakeStatus.DONE, active=True),
        ]
    )

    with pytest.raises(IntegrityError, match="ux_takes_one_active"):
        await session.flush()


async def test_only_a_done_take_can_be_active(session: AsyncSession) -> None:
    session.add(_take(_segment(_project()), attempt=1, status=TakeStatus.PENDING, active=True))

    with pytest.raises(IntegrityError, match="ck_takes_active_requires_done"):
        await session.flush()


async def test_same_attempt_cannot_be_inserted_twice(session: AsyncSession) -> None:
    segment = _segment(_project())
    session.add_all(
        [
            _take(segment, attempt=1, status=TakeStatus.PENDING, active=False),
            _take(segment, attempt=1, status=TakeStatus.PENDING, active=False),
        ]
    )

    with pytest.raises(IntegrityError, match="uq_takes_segment_id_segment_version_attempt"):
        await session.flush()


async def test_deleting_a_take_keeps_its_ledger_entry(session: AsyncSession) -> None:
    project = _project()
    take = _take(_segment(project), attempt=1, status=TakeStatus.DONE, active=False)
    entry = LedgerEntry(
        project=project,
        take=None,
        kind=LedgerKind.TTS,
        credits=7,
        idempotency_key=str(uuid.uuid4()),
    )
    session.add_all([take, entry])
    await session.flush()
    entry.take_id = take.id
    await session.flush()

    await session.execute(delete(Take).where(Take.id == take.id))  # DB-level, bypasses the ORM

    # Re-read from the database rather than the narrowed `entry.take_id` (mypy knows we just
    # assigned a UUID to it and would treat `is None` as unreachable).
    row = (
        await session.execute(
            select(LedgerEntry.take_id, LedgerEntry.credits).where(LedgerEntry.id == entry.id)
        )
    ).one()
    assert row.take_id is None
    assert row.credits == 7


async def test_deleting_a_project_cascades_to_segments(session: AsyncSession) -> None:
    project = _project()
    session.add_all([_segment(project, 0), _segment(project, 1)])
    await session.flush()

    await session.execute(delete(Project).where(Project.id == project.id))

    remaining = await session.scalar(
        select(func.count()).select_from(Segment).where(Segment.project_id == project.id)
    )
    assert remaining == 0
