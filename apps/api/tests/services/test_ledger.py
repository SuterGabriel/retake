"""LedgerService: reservation before the API call, settlement after, idempotency, local budget.

Contract (docs/ELEVENLABS.md impact points 1, 5, 12; ADR-0001 confirmation):
    LedgerService(session, settings, now=...)
      .reserve(project_id=, kind=, segment_id=, segment_version=, attempt=, estimated_credits=)
          -> Reservation(entry, created); entry pending, credits=0, estimated_credits=...
          raises BudgetExceeded, LedgerLocked
      .settle(entry_id, credits=, request_id=, take_id=)
          -> status done, credits = header value
      .mark_failed(entry_id, reason=)          -> status failed, credits 0
      .mark_possibly_billed(entry_id, request_id=)
          -> status possibly_billed, credits = estimate
      .spent(period=None, project_id=None)     -> int: done credits + pending/possibly_billed
      LedgerService.idempotency_key(kind, segment_id, version, attempt)
          -> "kind:segment:version:attempt"

Most tests run on the rolled-back savepoint session from conftest.py. The concurrency tests need
two real sessions with real commits and clean up after themselves (period 2099-01, never a real
month).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from retake.config import Settings, get_settings
from retake.db.models import (
    BudgetPeriod,
    LedgerEntry,
    LedgerKind,
    LedgerStatus,
    Project,
    Segment,
    Take,
    TakeStatus,
)
from retake.services.errors import BudgetExceeded, ErrorCode, LedgerEntryNotFound
from retake.services.ledger import LedgerService, Reservation


class ReserveArgs(TypedDict):
    project_id: uuid.UUID
    kind: LedgerKind
    segment_id: uuid.UUID
    segment_version: int
    attempt: int
    estimated_credits: int


NOW = datetime(2099, 1, 15, 12, 0, tzinfo=UTC)  # period "2099-01"
LAST_MONTH = datetime(2098, 12, 20, 12, 0, tzinfo=UTC)  # period "2098-12"


def settings_with_budget(budget: int) -> Settings:
    return Settings(elevenlabs_api_key="k", elevenlabs_monthly_budget=budget)


def clock(at: datetime) -> Callable[[], datetime]:
    return lambda: at


async def make_project(session: AsyncSession) -> Project:
    project = Project(title="Ledger test", voice_id="v", model_id="m")
    session.add(project)
    await session.flush()
    return project


async def make_take(session: AsyncSession, project: Project) -> Take:
    segment = Segment(
        project=project, position=0, paragraph_index=0, text="One.", normalized_text="one"
    )
    take = Take(
        segment=segment,
        segment_version=1,
        attempt=1,
        status=TakeStatus.PENDING,
        content_hash="0" * 64,
    )
    session.add_all([segment, take])
    await session.flush()
    return take


async def reserve(
    service: LedgerService, project: Project, *, estimate: int, attempt: int = 1
) -> LedgerEntry:
    reservation = await service.reserve(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=uuid.uuid4(),
        segment_version=1,
        attempt=attempt,
        estimated_credits=estimate,
    )
    return reservation.entry


async def count_entries(session: AsyncSession, project_id: uuid.UUID) -> int:
    n = await session.scalar(
        select(func.count()).select_from(LedgerEntry).where(LedgerEntry.project_id == project_id)
    )
    return n or 0


# ---------------------------------------------------------------- reserve / settle


async def test_reserve_writes_a_pending_entry_with_the_estimate(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    segment_id = uuid.uuid4()

    reservation = await service.reserve(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segment_id,
        segment_version=2,
        attempt=1,
        estimated_credits=79,
    )

    assert isinstance(reservation, Reservation)
    assert reservation.created is True
    entry = reservation.entry
    stored = await session.get(LedgerEntry, entry.id)
    assert stored is not None
    assert stored.status == LedgerStatus.PENDING
    assert stored.estimated_credits == 79
    assert stored.credits == 0  # nothing is known to be billed yet
    assert stored.kind == LedgerKind.TTS
    assert stored.period == "2099-01"
    assert stored.idempotency_key == f"tts:{segment_id}:2:1"
    assert stored.request_id is None
    assert stored.take_id is None


async def test_settle_stores_the_header_cost_never_the_estimate(session: AsyncSession) -> None:
    project = await make_project(session)
    take = await make_take(session, project)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    entry = await reserve(service, project, estimate=79)

    settled = await service.settle(entry.id, credits=81, request_id="req-1", take_id=take.id)

    assert settled.status == LedgerStatus.DONE
    assert settled.credits == 81
    assert settled.estimated_credits == 79  # the estimate stays for later comparison
    assert settled.request_id == "req-1"
    assert settled.take_id == take.id


async def test_settle_unknown_entry_raises(session: AsyncSession) -> None:
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))

    with pytest.raises(LedgerEntryNotFound):
        await service.settle(uuid.uuid4(), credits=1, request_id=None)


async def test_settle_twice_is_rejected(session: AsyncSession) -> None:
    """A settled entry is a fact; settling again with another number would rewrite history."""
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    entry = await reserve(service, project, estimate=10)
    await service.settle(entry.id, credits=10, request_id="req-1")

    with pytest.raises(ValueError, match="already"):
        await service.settle(entry.id, credits=99, request_id="req-2")


async def test_mark_failed_releases_the_reservation(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(100), now=clock(NOW))
    entry = await reserve(service, project, estimate=60)
    assert await service.spent() == 60

    failed = await service.mark_failed(entry.id, reason="http_401")

    assert failed.status == LedgerStatus.FAILED
    assert failed.credits == 0
    assert await service.spent() == 0
    assert (await reserve(service, project, estimate=100)).status == LedgerStatus.PENDING


async def test_mark_possibly_billed_keeps_the_estimate_against_the_budget(
    session: AsyncSession,
) -> None:
    """Read-side transport error (adapter raised PossiblyBilled): assume the worst, keep the
    reservation, and let the next job attempt reserve under a new key."""
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(100), now=clock(NOW))
    entry = await reserve(service, project, estimate=60)

    kept = await service.mark_possibly_billed(entry.id, request_id=None)

    assert kept.status == LedgerStatus.POSSIBLY_BILLED
    assert kept.credits == 60  # worst case is booked, not zero
    assert await service.spent() == 60
    with pytest.raises(BudgetExceeded):
        await reserve(service, project, estimate=50, attempt=2)
    assert (await reserve(service, project, estimate=40, attempt=2)).status == LedgerStatus.PENDING


# ---------------------------------------------------------------- idempotency


async def test_reserve_twice_with_same_key_returns_the_existing_entry(
    session: AsyncSession,
) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    segment_id = uuid.uuid4()
    kwargs = ReserveArgs(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segment_id,
        segment_version=1,
        attempt=1,
        estimated_credits=50,
    )

    first = await service.reserve(**kwargs)
    second = await service.reserve(**kwargs)

    assert first.created is True
    assert second.created is False  # the caller must not call the API again on this attempt
    assert second.entry.id == first.entry.id
    assert second.entry.status == LedgerStatus.PENDING
    assert await count_entries(session, project.id) == 1
    assert await service.spent() == 50  # not 100: the duplicate delivery cost nothing


async def test_reserve_after_settle_with_same_key_returns_the_settled_entry(
    session: AsyncSession,
) -> None:
    """Duplicate job delivery after the first run finished: the caller gets the done entry and
    can skip the API call entirely."""
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    segment_id = uuid.uuid4()
    kwargs = ReserveArgs(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segment_id,
        segment_version=1,
        attempt=1,
        estimated_credits=50,
    )
    first = (await service.reserve(**kwargs)).entry
    await service.settle(first.id, credits=50, request_id="req-1")

    again = await service.reserve(**kwargs)

    assert again.created is False
    assert again.entry.id == first.id
    assert again.entry.status == LedgerStatus.DONE


async def test_reserve_after_mark_failed_returns_the_failed_entry(session: AsyncSession) -> None:
    """A failed attempt is a fact too. Same key -> same row; a retry must use attempt + 1."""
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    segment_id = uuid.uuid4()
    kwargs = ReserveArgs(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segment_id,
        segment_version=1,
        attempt=1,
        estimated_credits=50,
    )
    first = (await service.reserve(**kwargs)).entry
    await service.mark_failed(first.id, reason="http_401")

    again = await service.reserve(**kwargs)

    assert again.created is False
    assert again.entry.id == first.id
    assert again.entry.status == LedgerStatus.FAILED
    assert await count_entries(session, project.id) == 1
    retry_args = kwargs.copy()
    retry_args["attempt"] = 2
    retry = await service.reserve(**retry_args)
    assert retry.created is True
    assert retry.entry.id != first.id
    assert retry.entry.status == LedgerStatus.PENDING


async def test_new_attempt_is_a_new_entry(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    segment_id = uuid.uuid4()

    a1 = (
        await service.reserve(
            project_id=project.id,
            kind=LedgerKind.TTS,
            segment_id=segment_id,
            segment_version=1,
            attempt=1,
            estimated_credits=50,
        )
    ).entry
    a2 = (
        await service.reserve(
            project_id=project.id,
            kind=LedgerKind.TTS,
            segment_id=segment_id,
            segment_version=1,
            attempt=2,
            estimated_credits=50,
        )
    ).entry

    assert a1.id != a2.id
    assert await count_entries(session, project.id) == 2


def test_idempotency_key_format() -> None:
    segment_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    key = LedgerService.idempotency_key(LedgerKind.STT, segment_id, 3, 2)

    assert key == "stt:12345678-1234-5678-1234-567812345678:3:2"


# ---------------------------------------------------------------- budget


async def test_budget_counts_done_and_pending_entries(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    done = await reserve(service, project, estimate=100)
    await service.settle(done.id, credits=120, request_id="r")  # real cost, not the estimate
    await reserve(service, project, estimate=30)  # still pending

    assert await service.spent() == 150


async def test_reserve_exactly_at_the_limit_is_allowed(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(100), now=clock(NOW))
    await reserve(service, project, estimate=60)

    entry = await reserve(service, project, estimate=40)  # 60 + 40 == 100

    assert entry.status == LedgerStatus.PENDING
    assert await service.spent() == 100


async def test_reserve_one_over_the_limit_raises_budget_exceeded(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(100), now=clock(NOW))
    await reserve(service, project, estimate=60)

    with pytest.raises(BudgetExceeded) as info:
        await reserve(service, project, estimate=41)

    assert info.value.code == ErrorCode.BUDGET_EXCEEDED
    assert "41" in info.value.detail and "40" in info.value.detail  # asked vs. remaining
    assert await count_entries(session, project.id) == 1  # nothing was written
    assert await service.spent() == 60


async def test_budget_is_per_period_previous_month_does_not_count(session: AsyncSession) -> None:
    project = await make_project(session)
    settings = settings_with_budget(100)
    december = LedgerService(session, settings, now=clock(LAST_MONTH))
    january = LedgerService(session, settings, now=clock(NOW))
    await reserve(december, project, estimate=90)

    assert await december.spent() == 90
    assert await january.spent() == 0
    assert (await reserve(january, project, estimate=100)).period == "2099-01"


async def test_budget_is_shared_across_projects(session: AsyncSession) -> None:
    project_a = await make_project(session)
    project_b = await make_project(session)
    service = LedgerService(session, settings_with_budget(100), now=clock(NOW))
    await reserve(service, project_a, estimate=70)

    with pytest.raises(BudgetExceeded):
        await reserve(service, project_b, estimate=40)


async def test_spent_can_be_queried_for_a_project(session: AsyncSession) -> None:
    project_a = await make_project(session)
    project_b = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    await reserve(service, project_a, estimate=70)
    await reserve(service, project_b, estimate=20)

    assert await service.spent(project_id=project_a.id) == 70
    assert await service.spent() == 90


# ---------------------------------------------------------------- integers only


@pytest.mark.parametrize("bad", [12.5, "12", True])
async def test_reserve_rejects_non_integer_estimates(session: AsyncSession, bad: object) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))

    with pytest.raises(TypeError):
        await service.reserve(
            project_id=project.id,
            kind=LedgerKind.TTS,
            segment_id=uuid.uuid4(),
            segment_version=1,
            attempt=1,
            estimated_credits=bad,  # type: ignore[arg-type]
        )


async def test_settle_rejects_non_integer_credits(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    entry = await reserve(service, project, estimate=10)

    with pytest.raises(TypeError):
        await service.settle(entry.id, credits=10.0, request_id=None)  # type: ignore[arg-type]


async def test_negative_estimate_is_rejected(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))

    with pytest.raises(ValueError):
        await reserve(service, project, estimate=-1)


async def test_spent_returns_an_int_even_when_empty(session: AsyncSession) -> None:
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))

    total = await service.spent()

    assert total == 0
    assert type(total) is int


# ---------------------------------------------------------------- budget_periods, real concurrency
# These tests commit for real, so they use their own sessions and clean up in `finally`.

TEST_PERIOD = "2099-01"


@pytest.fixture
async def real_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(Project).where(Project.title == "Ledger test"))
            await cleanup.execute(delete(BudgetPeriod).where(BudgetPeriod.period == TEST_PERIOD))
            await cleanup.commit()
        await engine.dispose()


async def test_first_reservation_creates_the_period_row_second_finds_it(
    real_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def period_rows(s: AsyncSession) -> int:
        n = await s.scalar(
            select(func.count()).select_from(BudgetPeriod).where(BudgetPeriod.period == TEST_PERIOD)
        )
        return n or 0

    async with real_sessions() as s:
        assert await period_rows(s) == 0
        project = await make_project(s)
        await s.commit()
        service = LedgerService(s, settings_with_budget(1000), now=clock(NOW))

        await reserve(service, project, estimate=10)
        assert await period_rows(s) == 1

        await reserve(service, project, estimate=10)
        assert await period_rows(s) == 1


async def test_concurrent_first_access_creates_exactly_one_period_row(
    real_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with real_sessions() as setup:
        project = await make_project(setup)
        await setup.commit()

    async def reserve_in_own_session() -> LedgerEntry:
        async with real_sessions() as s:
            service = LedgerService(s, settings_with_budget(1000), now=clock(NOW))
            return await reserve(service, project, estimate=10)

    entries = await asyncio.gather(*(reserve_in_own_session() for _ in range(4)))

    async with real_sessions() as check:
        rows = await check.scalar(
            select(func.count()).select_from(BudgetPeriod).where(BudgetPeriod.period == TEST_PERIOD)
        )
        assert rows == 1
        assert len({e.id for e in entries}) == 4


async def test_second_reservation_waits_for_the_lock_and_sees_the_updated_budget(
    real_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Session A holds the period row lock while B calls reserve(). B must block (not finish)
    until A commits, and then decide on the budget *including* what A wrote."""
    budget = settings_with_budget(100)
    async with real_sessions() as setup:
        project = await make_project(setup)
        service = LedgerService(setup, budget, now=clock(NOW))
        await reserve(service, project, estimate=10)  # creates the period row, spent = 10
        await setup.commit()

    async with real_sessions() as a, real_sessions() as b:
        # A: take the row lock by hand and keep the transaction open
        await a.execute(
            select(BudgetPeriod).where(BudgetPeriod.period == TEST_PERIOD).with_for_update()
        )
        service_b = LedgerService(b, budget, now=clock(NOW))
        b_task = asyncio.create_task(reserve(service_b, project, estimate=50))

        try:
            await asyncio.sleep(0.2)
            assert not b_task.done(), "B must wait for A's row lock"
        except BaseException:
            b_task.cancel()
            raise

        # A: reserve 60 of the remaining 90 inside the same transaction (it already holds the
        # lock, so FOR UPDATE inside reserve() does not block) and commit, releasing the lock
        service_a = LedgerService(a, budget, now=clock(NOW))
        await reserve(service_a, project, estimate=60)

        # B wakes up, sees 70 spent, 50 more would be 120 > 100
        with pytest.raises(BudgetExceeded):
            await b_task

    async with real_sessions() as check:
        service = LedgerService(check, budget, now=clock(NOW))
        assert await service.spent() == 70


async def test_mark_failed_and_possibly_billed_reject_settled_entries(
    session: AsyncSession,
) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    entry = await reserve(service, project, estimate=10)
    await service.settle(entry.id, credits=10, request_id="r")

    with pytest.raises(ValueError, match="already done"):
        await service.mark_failed(entry.id, reason="late")
    with pytest.raises(ValueError, match="already done"):
        await service.mark_possibly_billed(entry.id, request_id=None)


async def test_duplicate_reserve_does_not_keep_the_period_locked(
    real_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The reviewer's blocker: an early return inside a SAVEPOINT kept the FOR UPDATE lock on the
    caller's open transaction. After a duplicate reserve(), another session must be able to
    lock the period row immediately (NOWAIT)."""
    async with real_sessions() as setup:
        project = await make_project(setup)
        await setup.commit()

    async with real_sessions() as a, real_sessions() as b:
        service = LedgerService(a, settings_with_budget(1000), now=clock(NOW))
        segment_id = uuid.uuid4()
        kwargs = ReserveArgs(
            project_id=project.id,
            kind=LedgerKind.TTS,
            segment_id=segment_id,
            segment_version=1,
            attempt=1,
            estimated_credits=10,
        )
        await service.reserve(**kwargs)
        duplicate = await service.reserve(**kwargs)
        assert duplicate.created is False
        assert not a.in_transaction()  # reserve() ended the transaction on every path

        row = await b.execute(
            select(BudgetPeriod)
            .where(BudgetPeriod.period == TEST_PERIOD)
            .with_for_update(nowait=True)
        )
        assert row.scalar_one().period == TEST_PERIOD  # would raise LockNotAvailable if held
        await b.rollback()


async def test_budget_exceeded_does_not_keep_the_period_locked(
    real_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with real_sessions() as setup:
        project = await make_project(setup)
        await setup.commit()

    async with real_sessions() as a, real_sessions() as b:
        service = LedgerService(a, settings_with_budget(10), now=clock(NOW))
        await reserve(service, project, estimate=10)
        with pytest.raises(BudgetExceeded):
            await reserve(service, project, estimate=1)
        assert not a.in_transaction()

        row = await b.execute(
            select(BudgetPeriod)
            .where(BudgetPeriod.period == TEST_PERIOD)
            .with_for_update(nowait=True)
        )
        assert row.scalar_one().period == TEST_PERIOD
        await b.rollback()


# ---------------------------------------------------------------- record_free (cache hits)


async def test_record_free_writes_a_done_entry_without_touching_the_budget(
    session: AsyncSession,
) -> None:
    """A cache hit costs nothing, so it must never be refused by the budget: the budget here
    is smaller than the estimate on purpose. The estimate is still recorded so the saving
    stays visible ("this is what it would have cost")."""
    project = await make_project(session)
    take = await make_take(session, project)
    service = LedgerService(session, settings_with_budget(5), now=clock(NOW))

    entry = await service.record_free(
        project_id=project.id,
        kind=LedgerKind.CACHE_HIT,
        segment_id=take.segment_id,
        segment_version=1,
        attempt=2,
        estimated_credits=79,
        take_id=take.id,
    )

    stored = await session.get(LedgerEntry, entry.id)
    assert stored is not None
    assert stored.status == LedgerStatus.DONE
    assert stored.kind == LedgerKind.CACHE_HIT
    assert stored.credits == 0
    assert stored.estimated_credits == 79
    assert stored.take_id == take.id
    assert stored.period == "2099-01"
    assert stored.idempotency_key == f"cache_hit:{take.segment_id}:1:2"
    assert await service.spent(period="2099-01") == 0


async def test_record_free_twice_with_same_key_returns_the_existing_entry(
    session: AsyncSession,
) -> None:
    project = await make_project(session)
    take = await make_take(session, project)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))
    args: dict[str, Any] = dict(
        project_id=project.id,
        kind=LedgerKind.CACHE_HIT,
        segment_id=take.segment_id,
        segment_version=1,
        attempt=1,
        estimated_credits=10,
        take_id=take.id,
    )

    first = await service.record_free(**args)
    second = await service.record_free(**args)

    assert second.id == first.id
    assert await count_entries(session, project.id) == 1


async def test_record_free_rejects_non_integer_estimates(session: AsyncSession) -> None:
    project = await make_project(session)
    service = LedgerService(session, settings_with_budget(1000), now=clock(NOW))

    with pytest.raises(TypeError):
        await service.record_free(
            project_id=project.id,
            kind=LedgerKind.CACHE_HIT,
            segment_id=uuid.uuid4(),
            segment_version=1,
            attempt=1,
            estimated_credits=7.5,  # type: ignore[arg-type]
            take_id=None,
        )
