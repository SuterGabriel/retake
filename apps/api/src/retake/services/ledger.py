"""LedgerService: every credit spent or reserved is a row here (hard rule 2).

Pending pattern (docs/ELEVENLABS.md impact point 5):
  reserve()  before the API call: status pending, estimated_credits = len(text), credits = 0.
             Pending entries count against the budget, because the money is as good as spent.
  settle()   after a 2xx: credits = character-cost header, status done. Never the estimate.
  mark_failed()          nothing was billed: credits 0, budget released.
  mark_possibly_billed() the adapter raised PossiblyBilled: assume the worst, credits = estimate.

Budget (R21, impact point 12): local only. `ELEVENLABS_MONTHLY_BUDGET` minus everything booked
in the current period. Check and insert are serialised per period with a row lock on
`budget_periods` (SELECT ... FOR UPDATE), so two workers cannot both see "enough left".

Idempotency (R7): the key `kind:segment_id:version:attempt` is UNIQUE. A duplicate delivery of
the same attempt returns the existing row with `created=False`; the caller must look at its
status (a PENDING duplicate means the first run died between the API call and settle(): do not
call the API again on that attempt, use attempt + 1). A new attempt is a new row on purpose.

Transaction contract: every public method ends the session's transaction with commit(); a
refused reservation rolls back only its SAVEPOINT (which releases the row lock) and then commits
the empty outer transaction, so the caller's objects are never expired. Row locks live on the
transaction, not on a released SAVEPOINT, so an early return without ending the transaction
would keep the period locked (the class of bug a two-session test catches and a savepoint
fixture never will). Batch reservation for N segments (one lock, all-or-nothing) is task 8's
call; until then the caller reserves per segment.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import NamedTuple

import structlog
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from retake.config import Settings
from retake.db.models import BudgetPeriod, LedgerEntry, LedgerKind, LedgerStatus
from retake.services.errors import BudgetExceeded, LedgerEntryNotFound, LedgerLocked

log = structlog.get_logger(__name__)

# How long reserve() waits for another worker's reservation to commit before giving up.
# Bounded so one stuck worker cannot stall every other one forever.
LOCK_TIMEOUT = "5s"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _require_int(value: object, name: str) -> int:
    """Credits are integers, never floats, never bools (hard rule 7)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


class Reservation(NamedTuple):
    entry: LedgerEntry
    created: bool  # False: an entry with this key already existed (duplicate delivery)


class LedgerService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._session = session
        self._budget = settings.elevenlabs_monthly_budget
        self._now = now

    @staticmethod
    def idempotency_key(
        kind: LedgerKind, segment_id: uuid.UUID, segment_version: int, attempt: int
    ) -> str:
        return f"{kind.value}:{segment_id}:{segment_version}:{attempt}"

    def current_period(self) -> str:
        # Worker wall clock, not the database clock: at a month boundary two workers may
        # disagree by a few seconds. Acceptable for v1; the budget is a soft monthly cap.
        return self._now().strftime("%Y-%m")

    # ---------------------------------------------------------------- reserve

    async def reserve(
        self,
        *,
        project_id: uuid.UUID,
        kind: LedgerKind,
        segment_id: uuid.UUID,
        segment_version: int,
        attempt: int,
        estimated_credits: int,
    ) -> Reservation:
        """Book the estimate against this period's budget.

        Returns `Reservation(entry, created)`. `created=False` means the key already existed;
        nothing was booked and the caller must inspect `entry.status`.
        Raises `BudgetExceeded` (nothing written) or `LedgerLocked` (lock wait timed out).
        """
        estimate = _require_int(estimated_credits, "estimated_credits")
        key = self.idempotency_key(kind, segment_id, segment_version, attempt)
        period = self.current_period()

        # Idempotency lookup first: reading a UNIQUE key needs no lock, and it must not leave
        # a lock behind (see the module docstring).
        existing = await self._session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == key)
        )
        if existing is not None:
            await self._session.commit()
            log.info(
                "ledger.reserve.duplicate", key=key, status=existing.status.value, period=period
            )
            return Reservation(existing, created=False)

        # The locked section runs in a SAVEPOINT: rolling it back on refusal releases the row
        # lock without touching what the caller already holds in this transaction. Every path
        # then ends the transaction with commit(): a rollback() here would expire every ORM
        # object the caller has, and in async code the next attribute access becomes a
        # MissingGreenlet error. commit() with nothing to write only ends the transaction.
        spent = 0
        try:
            async with self._session.begin_nested():
                await self._ensure_period(period)
                await self._lock_period(period)
                spent = await self.spent(period=period)
                remaining = self._budget - spent
                if estimate > remaining:
                    raise BudgetExceeded(
                        f"Reserving {estimate} credits exceeds the remaining budget of "
                        f"{remaining} for period {period} (budget {self._budget}, booked {spent})"
                    )
                entry = LedgerEntry(
                    project_id=project_id,
                    kind=kind,
                    period=period,
                    status=LedgerStatus.PENDING,
                    estimated_credits=estimate,
                    credits=0,
                    idempotency_key=key,
                )
                self._session.add(entry)
                await self._session.flush()
            await self._session.commit()  # releases the row lock, entry is durable
        except BudgetExceeded:
            await self._session.commit()  # savepoint already rolled back; end the transaction
            log.warning(
                "ledger.reserve.budget_exceeded",
                period=period,
                asked=estimate,
                remaining=self._budget - spent,
                project_id=str(project_id),
            )
            raise
        except DBAPIError as exc:
            await self._session.commit()
            if _is_lock_timeout(exc):
                log.warning("ledger.reserve.lock_timeout", period=period, timeout=LOCK_TIMEOUT)
                raise LedgerLocked(
                    f"Could not lock budget period {period} within {LOCK_TIMEOUT}"
                ) from exc
            raise
        log.info(
            "ledger.reserve.created",
            key=key,
            period=period,
            estimated=estimate,
            project_id=str(project_id),
        )
        return Reservation(entry, created=True)

    async def record_free(
        self,
        *,
        project_id: uuid.UUID,
        kind: LedgerKind,
        segment_id: uuid.UUID,
        segment_version: int,
        attempt: int,
        estimated_credits: int,
        take_id: uuid.UUID | None,
    ) -> LedgerEntry:
        """Book an outcome that cost nothing (a cache hit): status done, credits 0.

        No budget check and no period lock, because zero credits can neither exceed nor race
        anything; a cache hit must never fail with "budget exceeded". `estimated_credits` is
        what the call would have cost, kept so the saving is visible in the ledger.
        Idempotent on the same key like `reserve()`: a duplicate returns the existing row.
        """
        estimate = _require_int(estimated_credits, "estimated_credits")
        key = self.idempotency_key(kind, segment_id, segment_version, attempt)
        period = self.current_period()

        existing = await self._session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == key)
        )
        if existing is not None:
            await self._session.commit()
            log.info("ledger.record_free.duplicate", key=key, status=existing.status.value)
            return existing

        await self._ensure_period(period)
        entry = LedgerEntry(
            project_id=project_id,
            take_id=take_id,
            kind=kind,
            period=period,
            status=LedgerStatus.DONE,
            estimated_credits=estimate,
            credits=0,
            idempotency_key=key,
        )
        self._session.add(entry)
        await self._session.commit()
        log.info(
            "ledger.record_free",
            key=key,
            kind=kind.value,
            period=period,
            estimated=estimate,
            project_id=str(project_id),
        )
        return entry

    async def _ensure_period(self, period: str) -> None:
        """Create the period row if missing. ON CONFLICT makes a concurrent first access safe."""
        stmt = (
            insert(BudgetPeriod)
            .values(period=period)
            .on_conflict_do_nothing(index_elements=[BudgetPeriod.period])
        )
        await self._session.execute(stmt)

    async def _lock_period(self, period: str) -> None:
        """Row lock until commit/rollback. `scalar_one` proves the row exists: FOR UPDATE on
        zero rows would lock nothing and silently disable the serialisation."""
        await self._session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        (
            await self._session.execute(
                select(BudgetPeriod).where(BudgetPeriod.period == period).with_for_update()
            )
        ).scalar_one()

    # ---------------------------------------------------------------- outcomes

    async def settle(
        self,
        entry_id: uuid.UUID,
        *,
        credits: int,
        request_id: str | None,
        take_id: uuid.UUID | None = None,
    ) -> LedgerEntry:
        """Record the cost the API reported. Only a pending entry can be settled."""
        billed = _require_int(credits, "credits")
        entry = await self._pending_entry(entry_id)
        entry.credits = billed
        entry.status = LedgerStatus.DONE
        entry.request_id = request_id
        if take_id is not None:
            entry.take_id = take_id
        await self._session.commit()
        log.info(
            "ledger.settle",
            key=entry.idempotency_key,
            credits=billed,
            estimated=entry.estimated_credits,
            request_id=request_id,
        )
        return entry

    async def mark_failed(self, entry_id: uuid.UUID, *, reason: str) -> LedgerEntry:
        """Nothing was billed (non-retryable error, or retries exhausted before any response).

        `reason` is an error *code* (e.g. "http_401", "paid_plan_required"), never a message:
        messages may echo response bodies and do not belong in the ledger (hard rule 1).
        """
        entry = await self._pending_entry(entry_id)
        entry.credits = 0
        entry.status = LedgerStatus.FAILED
        entry.failure_reason = reason[:255]
        await self._session.commit()
        log.info("ledger.failed", key=entry.idempotency_key, reason=entry.failure_reason)
        return entry

    async def mark_possibly_billed(
        self, entry_id: uuid.UUID, *, request_id: str | None
    ) -> LedgerEntry:
        """The request was sent but no response arrived: assume it was billed at the estimate.

        This is the event week-9 reconciliation looks for (by request id, if one exists).
        """
        entry = await self._pending_entry(entry_id)
        entry.credits = entry.estimated_credits
        entry.status = LedgerStatus.POSSIBLY_BILLED
        entry.request_id = request_id
        await self._session.commit()
        log.warning(
            "ledger.possibly_billed",
            key=entry.idempotency_key,
            credits=entry.credits,
            request_id=request_id,
        )
        return entry

    async def _pending_entry(self, entry_id: uuid.UUID) -> LedgerEntry:
        """Load an entry that may still change. A non-pending entry is a fact: changing it is
        a programming error (ValueError), not a client error."""
        entry = await self._session.get(LedgerEntry, entry_id)
        if entry is None:
            raise LedgerEntryNotFound(f"Ledger entry {entry_id} not found")
        if entry.status != LedgerStatus.PENDING:
            raise ValueError(f"Ledger entry {entry_id} is already {entry.status.value}")
        return entry

    # ---------------------------------------------------------------- reporting

    async def spent(self, *, period: str | None = None, project_id: uuid.UUID | None = None) -> int:
        """Credits booked in a period: done and possibly_billed at their credits, pending at
        the estimate, failed at zero."""
        booked = case(
            (LedgerEntry.status == LedgerStatus.PENDING, LedgerEntry.estimated_credits),
            (LedgerEntry.status == LedgerStatus.FAILED, 0),
            else_=LedgerEntry.credits,
        )
        stmt = select(func.coalesce(func.sum(booked), 0)).where(
            LedgerEntry.period == (period or self.current_period())
        )
        if project_id is not None:
            stmt = stmt.where(LedgerEntry.project_id == project_id)
        total = await self._session.scalar(stmt)
        return int(total or 0)


def _is_lock_timeout(exc: DBAPIError) -> bool:
    # asyncpg: LockNotAvailableError, SQLSTATE 55P03
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == "55P03" or "lock timeout" in str(exc.orig).lower()
