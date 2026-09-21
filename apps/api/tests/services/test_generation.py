"""GenerationService.generate_take: ledger + adapter + audio store as one unit of work.

Contract:
    GenerationService(session, ledger, tts, store).generate_take(segment_id, attempt=1) -> Take
      1. segment + project loaded (SegmentNotFound)
      2. cache: a done take with the same content_hash -> new done take reusing its audio,
         credits 0, ledger kind=cache_hit (credits 0, estimated_credits=len(text)), no API call
      3. ledger.reserve(); Reservation.created=False with status pending/failed/possibly_billed
         -> AttemptAlreadyInFlight (detail names attempt+1); with status done -> existing take
      4. take row committed as `generating` before the API call
      5. tts.synthesize(...) with previous/next segment text as context
         2xx -> audio stored, take done (+active if first), ledger settled with the header cost
         PossiblyBilled -> take failed, ledger possibly_billed
         other adapter errors -> take failed, ledger failed with the error code

Real Postgres (savepoint session from conftest), respx-mocked ElevenLabs, a temp-dir
LocalAudioStore, injected sleep so retries never wait.
"""

import base64
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from retake.config import Settings
from retake.db.models import (
    LedgerEntry,
    LedgerKind,
    LedgerStatus,
    Project,
    Segment,
    Take,
    TakeStatus,
)
from retake.domain.cache_key import content_hash
from retake.integrations.audio_store import LocalAudioStore
from retake.integrations.elevenlabs.client import build_client
from retake.integrations.elevenlabs.tts import TtsClient
from retake.services.errors import AttemptAlreadyInFlight, BudgetExceeded, SegmentNotFound
from retake.services.generation import GenerationService
from retake.services.ledger import LedgerService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "elevenlabs"
BASE_URL = "https://api.elevenlabs.io"
TTS_PATH = r"/v1/text-to-speech/.+/with-timestamps"
SENTENCES = ["First one.", "Second one.", "Third one."]


def tts_ok(cost: str = "79", request_id: str = "req-1") -> httpx.Response:
    body = json.loads((FIXTURES / "tts-with-timestamps.v2.json").read_text(encoding="utf-8"))
    return httpx.Response(
        200, json=body, headers={"character-cost": cost, "request-id": request_id}
    )


def tts_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status, json={"detail": {"type": code, "code": code, "message": "m", "status": code}}
    )


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with build_client("sk-test", base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def store(tmp_path: Path) -> LocalAudioStore:
    return LocalAudioStore(tmp_path / "audio")


@pytest.fixture
def settings() -> Settings:
    return Settings(elevenlabs_api_key="sk-test", elevenlabs_monthly_budget=1_000)


@pytest.fixture
def make_service(
    session: AsyncSession, http: httpx.AsyncClient, store: LocalAudioStore, settings: Settings
) -> Any:
    def _make(budget: int | None = None) -> GenerationService:
        s = (
            settings
            if budget is None
            else Settings(elevenlabs_api_key="sk", elevenlabs_monthly_budget=budget)
        )
        ledger = LedgerService(session, s)
        tts = TtsClient(
            http, concurrency=2, sleep=no_sleep, max_attempts=2, max_concurrency_waits=1
        )
        return GenerationService(session, ledger=ledger, tts=tts, store=store)

    return _make


async def make_project_with_segments(session: AsyncSession) -> tuple[Project, list[Segment]]:
    project = Project(
        title="Gen test",
        voice_id="voice-1",
        model_id="eleven_multilingual_v2",
        voice_settings={"stability": 0.7},
    )
    segments = [
        Segment(project=project, position=i, paragraph_index=0, text=t, normalized_text=t)
        for i, t in enumerate(SENTENCES)
    ]
    session.add_all([project, *segments])
    await session.commit()
    return project, segments


async def ledger_entries(session: AsyncSession, project_id: uuid.UUID) -> list[LedgerEntry]:
    rows = await session.scalars(
        select(LedgerEntry)
        .where(LedgerEntry.project_id == project_id)
        .order_by(LedgerEntry.created_at)
    )
    return list(rows)


async def take_count(session: AsyncSession, segment_id: uuid.UUID) -> int:
    n = await session.scalar(
        select(func.count()).select_from(Take).where(Take.segment_id == segment_id)
    )
    return n or 0


# ---------------------------------------------------------------- success


async def test_generate_stores_audio_settles_ledger_and_activates_first_take(
    session: AsyncSession, api: respx.MockRouter, make_service: Any, store: LocalAudioStore
) -> None:
    project, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok(cost="81", request_id="req-9"))

    take = await make_service().generate_take(segments[1].id)

    assert take.status == TakeStatus.DONE
    assert take.is_active is True  # first done take of the segment
    assert take.attempt == 1 and take.segment_version == 1
    assert take.duration_ms == 5619
    assert take.credits == 81
    assert take.request_id == "req-9"
    assert take.audio_key and await store.get(take.audio_key) == base64.b64decode("QUFBQQ==")
    assert take.content_hash == content_hash(
        text="Second one.",
        voice_id="voice-1",
        model_id="eleven_multilingual_v2",
        voice_settings={"stability": 0.7},
        previous_text="First one.",
        next_text="Third one.",
    )
    [entry] = await ledger_entries(session, project.id)
    assert (entry.kind, entry.status, entry.credits, entry.estimated_credits) == (
        LedgerKind.TTS,
        LedgerStatus.DONE,
        81,
        len("Second one."),
    )
    assert entry.take_id == take.id and entry.request_id == "req-9"
    assert route.call_count == 1


async def test_neighbouring_segments_are_sent_as_context(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())

    await make_service().generate_take(segments[0].id)  # first segment: no previous
    await make_service().generate_take(segments[2].id)  # last segment: no next

    first = json.loads(route.calls[0].request.content)
    last = json.loads(route.calls[1].request.content)
    assert "previous_text" not in first and first["next_text"] == "Second one."
    assert last["previous_text"] == "Second one." and "next_text" not in last
    assert first["voice_settings"] == {"stability": 0.7}
    assert route.calls[0].request.url.path.startswith("/v1/text-to-speech/voice-1/")


async def test_second_done_take_is_not_activated_automatically(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    """The user chooses between takes (R18); only the first done take auto-activates."""
    _, segments = await make_project_with_segments(session)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())

    first = await make_service().generate_take(segments[0].id, attempt=1)
    second = await make_service().generate_take(segments[0].id, attempt=2)

    assert first.is_active is True
    assert second.is_active is False
    # TODO(week 7, retake): with identical inputs attempt 2 is a cache hit and shares the audio.
    # A deliberate retake needs a `variant` dimension in content_hash so it produces new audio;
    # decide the shape in an ADR and then assert `second.audio_key != first.audio_key` here.


async def test_missing_cost_header_settles_with_the_estimate(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    project, segments = await make_project_with_segments(session)
    body = json.loads((FIXTURES / "tts-with-timestamps.v2.json").read_text(encoding="utf-8"))
    api.post(path__regex=TTS_PATH).mock(return_value=httpx.Response(200, json=body))

    take = await make_service().generate_take(segments[0].id)

    [entry] = await ledger_entries(session, project.id)
    assert entry.status == LedgerStatus.DONE
    assert entry.credits == len("First one.") == take.credits  # estimate, verified == cost live


# ---------------------------------------------------------------- cache


async def test_identical_request_reuses_audio_without_an_api_call(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    project, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok(cost="79"))
    original = await make_service().generate_take(segments[0].id, attempt=1)

    cached = await make_service().generate_take(segments[0].id, attempt=2)

    assert route.call_count == 1  # no second API call
    assert cached.status == TakeStatus.DONE
    assert cached.audio_key == original.audio_key
    assert cached.duration_ms == original.duration_ms
    assert cached.credits == 0
    assert cached.content_hash == original.content_hash
    assert cached.id != original.id
    entries = await ledger_entries(session, project.id)
    assert [e.kind for e in entries] == [LedgerKind.TTS, LedgerKind.CACHE_HIT]
    hit = entries[1]
    assert (hit.status, hit.credits, hit.estimated_credits) == (
        LedgerStatus.DONE,
        0,
        len("First one."),
    )  # the saving stays visible: estimated what it would have cost


async def test_changed_next_text_misses_the_cache(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    await make_service().generate_take(segments[0].id, attempt=1)

    segments[1].text = "Second one, edited."  # the neighbour changed -> different context
    await session.commit()
    regenerated = await make_service().generate_take(segments[0].id, attempt=2)

    assert route.call_count == 2
    assert regenerated.credits == 79


async def test_cache_hit_across_projects_with_same_voice_and_context(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments_a = await make_project_with_segments(session)
    _, segments_b = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())

    await make_service().generate_take(segments_a[0].id)
    reused = await make_service().generate_take(segments_b[0].id)

    assert route.call_count == 1
    assert reused.credits == 0


async def test_failed_take_is_not_a_cache_source(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(
        side_effect=[tts_error(401, "invalid_api_key"), tts_ok()]
    )
    await make_service().generate_take(segments[0].id, attempt=1)  # fails, take failed

    take = await make_service().generate_take(segments[0].id, attempt=2)

    assert route.call_count == 2
    assert take.status == TakeStatus.DONE


# ---------------------------------------------------------------- idempotency / attempts


async def test_duplicate_of_a_done_attempt_returns_the_existing_take(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    first = await make_service().generate_take(segments[0].id, attempt=1)

    again = await make_service().generate_take(segments[0].id, attempt=1)

    assert again.id == first.id
    assert route.call_count == 1
    assert await take_count(session, segments[0].id) == 1


async def test_pending_reservation_from_a_crashed_run_is_not_retried_on_the_same_attempt(
    session: AsyncSession, api: respx.MockRouter, make_service: Any, settings: Settings
) -> None:
    """Simulates a worker that died between the API call and settle(): the ledger has a pending
    entry for attempt 1. The same attempt must not call the API again (it may already be
    billed); the caller is told to use attempt + 1."""
    project, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    ledger = LedgerService(session, settings)
    await ledger.reserve(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segments[0].id,
        segment_version=1,
        attempt=1,
        estimated_credits=len("First one."),
    )

    with pytest.raises(AttemptAlreadyInFlight) as info:
        await make_service().generate_take(segments[0].id, attempt=1)

    assert "attempt 2" in info.value.detail
    assert route.call_count == 0
    assert await take_count(session, segments[0].id) == 0


@pytest.mark.parametrize("terminal", ["failed", "possibly_billed"])
async def test_terminal_ledger_states_also_require_a_new_attempt(
    session: AsyncSession,
    api: respx.MockRouter,
    make_service: Any,
    settings: Settings,
    terminal: str,
) -> None:
    project, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    ledger = LedgerService(session, settings)
    reservation = await ledger.reserve(
        project_id=project.id,
        kind=LedgerKind.TTS,
        segment_id=segments[0].id,
        segment_version=1,
        attempt=1,
        estimated_credits=10,
    )
    if terminal == "failed":
        await ledger.mark_failed(reservation.entry.id, reason="http_401")
    else:
        await ledger.mark_possibly_billed(reservation.entry.id, request_id=None)

    with pytest.raises(AttemptAlreadyInFlight):
        await make_service().generate_take(segments[0].id, attempt=1)

    assert route.call_count == 0


# ---------------------------------------------------------------- failures


async def test_budget_exceeded_makes_no_take_and_no_api_call(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    _, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())

    with pytest.raises(BudgetExceeded):
        await make_service(budget=5).generate_take(segments[0].id)  # "First one." is 10 chars

    assert route.call_count == 0
    assert await take_count(session, segments[0].id) == 0


async def test_non_retryable_error_marks_take_and_ledger_failed(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    project, segments = await make_project_with_segments(session)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_error(402, "paid_plan_required"))

    take = await make_service().generate_take(segments[0].id)

    assert take.status == TakeStatus.FAILED
    assert take.is_active is False and take.audio_key is None and take.credits == 0
    [entry] = await ledger_entries(session, project.id)
    assert (entry.status, entry.credits, entry.failure_reason) == (
        LedgerStatus.FAILED,
        0,
        "paid_plan_required",
    )


async def test_exhausted_retries_mark_take_and_ledger_failed(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    project, segments = await make_project_with_segments(session)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_error(503, "server_error"))

    take = await make_service().generate_take(segments[0].id)

    assert route.call_count == 2  # max_attempts in the fixture
    assert take.status == TakeStatus.FAILED
    [entry] = await ledger_entries(session, project.id)
    assert entry.status == LedgerStatus.FAILED and entry.failure_reason == "server_error"


async def test_possibly_billed_keeps_the_reservation(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    project, segments = await make_project_with_segments(session)
    api.post(path__regex=TTS_PATH).mock(side_effect=httpx.ReadTimeout("slow"))

    take = await make_service().generate_take(segments[0].id)

    assert take.status == TakeStatus.FAILED
    [entry] = await ledger_entries(session, project.id)
    assert entry.status == LedgerStatus.POSSIBLY_BILLED
    assert entry.credits == len("First one.")  # worst case stays booked
    ledger = LedgerService(session, Settings(elevenlabs_api_key="k"))
    assert await ledger.spent(project_id=project.id) == len("First one.")


async def test_unknown_segment_raises_not_found(make_service: Any) -> None:
    with pytest.raises(SegmentNotFound):
        await make_service().generate_take(uuid.uuid4())


async def test_take_row_exists_before_the_api_call(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    """The take (like the ledger entry) is committed as `generating` before money is spent, so
    a crash mid-call leaves a visible trace instead of nothing."""
    _, segments = await make_project_with_segments(session)
    seen: list[TakeStatus] = []

    async def observe(request: httpx.Request) -> httpx.Response:
        row = await session.scalar(select(Take).where(Take.segment_id == segments[0].id))
        seen.append(row.status if row else TakeStatus.FAILED)
        return tts_ok()

    api.post(path__regex=TTS_PATH).mock(side_effect=observe)

    await make_service().generate_take(segments[0].id)

    assert seen == [TakeStatus.GENERATING]


# ---------------------------------------------------------------- after the money is spent


async def test_unusable_2xx_is_booked_as_possibly_billed(
    session: AsyncSession, api: respx.MockRouter, make_service: Any
) -> None:
    """A 200 with a body we cannot use (here: a non-integer cost header) was billed by the
    server; the ledger must keep the estimate booked, never release it as `failed`."""
    project, segments = await make_project_with_segments(session)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok(cost="not-a-number"))

    take = await make_service().generate_take(segments[0].id)

    assert take.status == TakeStatus.FAILED and take.audio_key is None
    [entry] = await ledger_entries(session, project.id)
    assert entry.status == LedgerStatus.POSSIBLY_BILLED
    assert entry.credits == len("First one.")


class BrokenStore(LocalAudioStore):
    async def put(self, key: str, data: bytes) -> None:
        raise OSError("disk full")


async def test_store_failure_after_a_billed_call_settles_the_ledger_and_fails_the_take(
    session: AsyncSession,
    api: respx.MockRouter,
    http: httpx.AsyncClient,
    settings: Settings,
    tmp_path: Path,
) -> None:
    """The API answered 2xx (billed) but the audio could not be stored: the real cost is
    settled, the take is terminal, and the caller still sees the infrastructure error."""
    project, segments = await make_project_with_segments(session)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok(cost="81", request_id="req-9"))
    tts = TtsClient(http, concurrency=2, sleep=no_sleep, max_attempts=2, max_concurrency_waits=1)
    service = GenerationService(
        session, ledger=LedgerService(session, settings), tts=tts, store=BrokenStore(tmp_path)
    )

    with pytest.raises(OSError):
        await service.generate_take(segments[0].id)

    [take] = list(await session.scalars(select(Take).where(Take.segment_id == segments[0].id)))
    assert take.status == TakeStatus.FAILED and take.audio_key is None
    [entry] = await ledger_entries(session, project.id)
    assert (entry.status, entry.credits, entry.take_id) == (LedgerStatus.DONE, 81, take.id)
