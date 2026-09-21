"""GenerationService: one take for one segment, as one unit of work.

Ledger, ElevenLabs adapter and audio store are combined here and nowhere else. The order of
operations is the contract (tests/services/test_generation.py):

    1. load segment + project + neighbours   -> SegmentNotFound
    2. a take for (segment, version, attempt)? done -> return it; else AttemptAlreadyInFlight
    3. a done take with the same content_hash -> reuse its audio, ledger cache_hit, credits 0
    4. ledger.reserve()                        -> BudgetExceeded / AttemptAlreadyInFlight
    5. take committed as `generating`          (visible before money is spent)
    6. tts.synthesize()
         2xx                 -> audio stored, take done, ledger settled with the header cost
         PossiblyBilled      -> take failed, ledger possibly_billed
         other adapter error -> take failed, ledger failed with the error code

The service commits through the ledger: every ledger method ends the transaction, and the take
row is dirty in the same session, so take and ledger entry are always written together.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from retake.db.models import LedgerKind, Project, Segment, Take, TakeStatus
from retake.domain.cache_key import content_hash
from retake.integrations.audio_store import AudioStore
from retake.integrations.elevenlabs.errors import (
    ElevenLabsError,
    PossiblyBilled,
    UnexpectedResponse,
)
from retake.integrations.elevenlabs.tts import TtsClient
from retake.services.errors import AttemptAlreadyInFlight, SegmentNotFound
from retake.services.ledger import LedgerService

log = structlog.get_logger(__name__)


def audio_key_for(take_id: uuid.UUID) -> str:
    return f"takes/{take_id}.mp3"


class GenerationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        ledger: LedgerService,
        tts: TtsClient,
        store: AudioStore,
    ) -> None:
        self._session = session
        self._ledger = ledger
        self._tts = tts
        self._store = store

    async def generate_take(self, segment_id: uuid.UUID, attempt: int = 1) -> Take:
        """Generate (or reuse) audio for a segment and return the take, whatever its outcome.

        Adapter errors are not exceptions for the caller: they end as a `failed` take with the
        error code in the ledger's `failure_reason`. The worker job (week 3) reads that code to
        decide about attempt + 1: `possibly_billed` and `server_error` (retries exhausted) yes;
        `paid_plan_required` and other non-retryable 4xx no. Only use-case errors are raised:
        SegmentNotFound, AttemptAlreadyInFlight, BudgetExceeded, LedgerLocked.
        """
        segment = await self._session.get(Segment, segment_id)
        if segment is None:
            raise SegmentNotFound(f"Segment {segment_id} not found")
        project = await self._session.get(Project, segment.project_id)
        if project is None:  # the FK guarantees this; the check keeps mypy and the reader honest
            raise SegmentNotFound(f"Segment {segment_id} has no project")
        previous_text, next_text = await self._neighbour_texts(segment)
        digest = content_hash(
            text=segment.text,
            voice_id=project.voice_id,
            model_id=project.model_id,
            voice_settings=project.voice_settings,
            previous_text=previous_text,
            next_text=next_text,
        )

        existing = await self._take_for_attempt(segment, attempt)
        if existing is not None:
            if existing.status == TakeStatus.DONE:
                log.info("generation.duplicate_attempt", take_id=str(existing.id))
                return existing
            raise AttemptAlreadyInFlight(
                f"Attempt {attempt} for segment {segment.id} is already {existing.status.value}; "
                f"use attempt {attempt + 1}"
            )

        # TODO(week 3, worker): the cache path skips the ledger's "an attempt is a fact" rule.
        # A pending `tts:` entry for this attempt (a run that died after reserve()) plus a done
        # take with this hash elsewhere would book a second ledger row for the same attempt, and
        # two parallel requests for the same attempt end in an IntegrityError on the take insert
        # (500) instead of 409. Closed by test_parallel_same_attempt_returns_409: look the
        # ledger key up before the cache and turn the IntegrityError into AttemptAlreadyInFlight.
        source = await self._cached_take(digest)
        if source is not None:
            return await self._reuse(segment, project, attempt, digest, source)

        estimate = len(segment.text)
        reservation = await self._ledger.reserve(
            project_id=project.id,
            kind=LedgerKind.TTS,
            segment_id=segment.id,
            segment_version=segment.version,
            attempt=attempt,
            estimated_credits=estimate,
        )
        entry = reservation.entry
        if not reservation.created:
            # The ledger knows this attempt but step 2 found no done take for it: a run died
            # after reserving (pending, maybe billed), or ended in failed/possibly_billed.
            raise AttemptAlreadyInFlight(
                f"Attempt {attempt} for segment {segment.id} is already {entry.status.value} "
                f"in the ledger; use attempt {attempt + 1}"
            )

        take = Take(
            segment_id=segment.id,
            segment_version=segment.version,
            attempt=attempt,
            status=TakeStatus.GENERATING,
            content_hash=digest,
        )
        self._session.add(take)
        await self._session.commit()  # a crash from here on leaves a visible `generating` take

        try:
            result = await self._tts.synthesize(
                text=segment.text,
                voice_id=project.voice_id,
                model_id=project.model_id,
                voice_settings=project.voice_settings,
                previous_text=previous_text,
                next_text=next_text,
            )
        except (PossiblyBilled, UnexpectedResponse) as exc:
            # Both mean "the server may have billed us": no response after sending, or a 2xx
            # whose body we could not use. Listed before ElevenLabsError, their common base,
            # because `except` picks the first matching clause, not the most specific one.
            take.status = TakeStatus.FAILED
            await self._ledger.mark_possibly_billed(entry.id, request_id=exc.request_id)
            log.warning(
                "generation.possibly_billed",
                take_id=str(take.id),
                reason=type(exc).__name__,
                code=exc.code,
                attempts=exc.attempts,
            )
            return take
        except ElevenLabsError as exc:
            take.status = TakeStatus.FAILED
            await self._ledger.mark_failed(entry.id, reason=exc.code or "unknown")
            log.warning("generation.failed", take_id=str(take.id), code=exc.code, status=exc.status)
            return take

        # From here on the credits are spent. Every failure below must still end in a settled
        # ledger entry and a terminal take, never in pending/generating.
        # Verified live: the header is always sent. If it ever is not, the estimate is the best
        # known value; the ledger records it as done because the audio did arrive.
        credits = result.character_cost if result.character_cost is not None else estimate
        key = audio_key_for(take.id)
        try:
            await self._store.put(key, result.audio)
        except OSError as exc:
            take.status = TakeStatus.FAILED
            await self._ledger.settle(
                entry.id, credits=credits, request_id=result.request_id, take_id=take.id
            )
            log.error("generation.store_failed", take_id=str(take.id), reason=type(exc).__name__)
            raise  # infrastructure failure: the caller sees a 500, the books are right
        take.audio_key = key
        take.duration_ms = result.duration_ms
        take.credits = credits
        take.request_id = result.request_id
        take.status = TakeStatus.DONE
        # TODO(week 3, worker): check-then-act. Two parallel generations for different attempts
        # of one segment can both see "no active take"; the loser fails on ux_takes_one_active
        # inside settle()'s commit, after the call was billed. Closed by
        # test_parallel_attempts_activate_only_one: lock the segment row (SELECT ... FOR UPDATE)
        # before deciding, or retry the commit with is_active=False.
        take.is_active = not await self._has_active_take(segment.id)
        await self._ledger.settle(
            entry.id, credits=credits, request_id=result.request_id, take_id=take.id
        )
        log.info(
            "generation.done",
            take_id=str(take.id),
            credits=credits,
            duration_ms=take.duration_ms,
            attempts=result.attempts,
        )
        return take

    # ---------------------------------------------------------------- cache path

    async def _reuse(
        self, segment: Segment, project: Project, attempt: int, digest: str, source: Take
    ) -> Take:
        """A new take row (this segment, this attempt) that points at the audio of `source`."""
        take = Take(
            segment_id=segment.id,
            segment_version=segment.version,
            attempt=attempt,
            status=TakeStatus.DONE,
            content_hash=digest,
            audio_key=source.audio_key,
            duration_ms=source.duration_ms,
            credits=0,
            is_active=not await self._has_active_take(segment.id),
        )
        self._session.add(take)
        await self._session.flush()  # take.id for the ledger row
        await self._ledger.record_free(
            project_id=project.id,
            kind=LedgerKind.CACHE_HIT,
            segment_id=segment.id,
            segment_version=segment.version,
            attempt=attempt,
            estimated_credits=len(segment.text),
            take_id=take.id,
        )
        log.info("generation.cache_hit", take_id=str(take.id), source_take_id=str(source.id))
        return take

    # ---------------------------------------------------------------- queries

    async def _neighbour_texts(self, segment: Segment) -> tuple[str | None, str | None]:
        rows = await self._session.execute(
            select(Segment.position, Segment.text).where(
                Segment.project_id == segment.project_id,
                Segment.position.in_([segment.position - 1, segment.position + 1]),
            )
        )
        by_position = {position: text for position, text in rows}
        return by_position.get(segment.position - 1), by_position.get(segment.position + 1)

    async def _take_for_attempt(self, segment: Segment, attempt: int) -> Take | None:
        result = await self._session.scalars(
            select(Take).where(
                Take.segment_id == segment.id,
                Take.segment_version == segment.version,
                Take.attempt == attempt,
            )
        )
        return result.first()

    async def _cached_take(self, digest: str) -> Take | None:
        """Any done take with this hash, in any project: the audio is the same."""
        result = await self._session.scalars(
            select(Take)
            .where(
                Take.content_hash == digest,
                Take.status == TakeStatus.DONE,
                Take.audio_key.is_not(None),
            )
            .order_by(Take.created_at)
            .limit(1)
        )
        return result.first()

    async def _has_active_take(self, segment_id: uuid.UUID) -> bool:
        active = await self._session.scalar(
            select(Take.id).where(Take.segment_id == segment_id, Take.is_active.is_(True))
        )
        return active is not None
