"""The ledger migration's data backfill and its downgrade, exercised against the real database.

`alembic check` only compares schema, never data, so the backfill SQL in
`2026_09_17_2113-4fb6efeac138` would otherwise run for the first time in production.
Runs alembic as a subprocess (env.py starts its own event loop) and always leaves the
database at head.
"""

import asyncio
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from retake.config import get_settings

API_DIR = Path(__file__).resolve().parents[1]
INITIAL = "7140db651314"
LEGACY_PERIOD = "2026-08"


def alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr[-2000:]}"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(get_settings().database_url)
    try:
        yield eng
    finally:
        await asyncio.to_thread(alembic, "upgrade", "head")  # whatever happened, end at head
        async with eng.begin() as conn:
            await conn.execute(text("DELETE FROM projects WHERE title = 'migration probe'"))
            await conn.execute(
                text("DELETE FROM budget_periods WHERE period = :p"), {"p": LEGACY_PERIOD}
            )
        await eng.dispose()


async def test_ledger_migration_backfills_legacy_rows_and_round_trips(engine: AsyncEngine) -> None:
    project_id, entry_id = uuid.uuid4(), uuid.uuid4()

    # 1. Schema as it was before the ledger migration, with one legacy row (a settled cost).
    await asyncio.to_thread(alembic, "downgrade", INITIAL)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projects (id, title, voice_id, model_id) "
                "VALUES (:id, 'migration probe', 'v', 'm')"
            ),
            {"id": project_id},
        )
        await conn.execute(
            text(
                "INSERT INTO ledger_entries "
                "(id, project_id, kind, credits, idempotency_key, created_at) "
                "VALUES (:id, :pid, 'tts', 42, :key, :at)"
            ),
            {
                "id": entry_id,
                "pid": project_id,
                "key": f"tts:{uuid.uuid4()}:1:1",
                "at": datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
            },
        )

    # 2. Upgrade: the legacy row gets its period, is marked done, estimate == cost.
    await asyncio.to_thread(alembic, "upgrade", "head")
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT period, status, estimated_credits, credits, request_id "
                    "FROM ledger_entries WHERE id = :id"
                ),
                {"id": entry_id},
            )
        ).one()
        assert (row.period, row.status, row.estimated_credits, row.credits) == (
            LEGACY_PERIOD,
            "done",
            42,
            42,
        )
        assert row.request_id is None
        periods = (
            await conn.execute(
                text("SELECT period FROM budget_periods WHERE period = :p"), {"p": LEGACY_PERIOD}
            )
        ).all()
        assert len(periods) == 1

    # 3. Downgrade removes the new columns and the period table; the legacy row survives.
    await asyncio.to_thread(alembic, "downgrade", INITIAL)
    async with engine.connect() as conn:
        credits = await conn.scalar(
            text("SELECT credits FROM ledger_entries WHERE id = :id"), {"id": entry_id}
        )
        assert credits == 42
        columns = {
            r.column_name
            for r in await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'ledger_entries'"
                )
            )
        }
        assert {"period", "status", "estimated_credits", "request_id"} & columns == set()

    # 4. And up again (the fixture also does this in `finally`).
    await asyncio.to_thread(alembic, "upgrade", "head")
