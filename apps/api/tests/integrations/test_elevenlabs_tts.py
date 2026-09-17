"""Contract tests for the ElevenLabs TTS adapter, against the real response shapes captured in
tests/fixtures/elevenlabs (docs/ELEVENLABS.md, "verified (live)"). HTTP is mocked with respx;
no test ever reaches the network. Written before the implementation (TDD).

Interface under test:
    build_client(api_key, *, base_url) -> httpx.AsyncClient      (integrations/elevenlabs/client.py)
    TtsClient(http, concurrency=..., sleep=..., ...).synthesize(...) -> TtsResult   (tts.py)
    ElevenLabsError > RetryableError > RateLimited
    ElevenLabsError > PossiblyBilled
    ElevenLabsError > NonRetryableError > PlanRequired
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from retake.integrations.elevenlabs.client import build_client
from retake.integrations.elevenlabs.errors import (
    ElevenLabsError,
    NonRetryableError,
    PlanRequired,
    PossiblyBilled,
    RateLimited,
    RetryableError,
)
from retake.integrations.elevenlabs.tts import TtsClient, TtsResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "elevenlabs"
BASE_URL = "https://api.elevenlabs.io"
API_KEY = "sk-test-secret-never-logged"
TTS_PATH = r"/v1/text-to-speech/voice-1/with-timestamps"
TEXT = 'Chapter one. Dr. Zyphora arrived at 7:30 p.m. and said, "Nobody knows my name."'
VOICE_SETTINGS = {"stability": 0.7, "similarity_boost": 0.75, "style": 0.0, "speed": 1.0}


def fixture(name: str) -> dict[str, Any]:
    return dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def ok_response() -> httpx.Response:
    body = fixture("tts-with-timestamps.v2.json")
    headers = {"character-cost": "79", "request-id": "req-123", "content-type": "application/json"}
    return httpx.Response(200, json=body, headers=headers)


def error_response(status: int, code: str, message: str = "nope", **headers: str) -> httpx.Response:
    body = {"detail": {"type": code, "code": code, "message": message, "status": code}}
    return httpx.Response(status, json=body, headers=headers)


class FakeSleep:
    """Injectable sleep: records requested delays, never waits."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with build_client(API_KEY, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
def tts(http: httpx.AsyncClient, sleep: FakeSleep) -> TtsClient:
    return TtsClient(http, concurrency=2, sleep=sleep, max_attempts=3, max_concurrency_waits=3)


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


async def synthesize(tts: TtsClient, **overrides: Any) -> TtsResult:
    return await tts.synthesize(
        text=TEXT,
        voice_id="voice-1",
        model_id="eleven_multilingual_v2",
        voice_settings=VOICE_SETTINGS,
        **overrides,
    )


# ---------------------------------------------------------------- 200


async def test_success_returns_audio_alignment_duration_cost_and_request_id(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(return_value=ok_response())

    result = await synthesize(tts)

    assert result.audio == base64.b64decode("QUFBQQ==")  # the fixture's placeholder audio
    assert len(result.alignment.characters) == len(TEXT)  # alignment covers exactly the input
    assert result.alignment.characters[:7] == tuple("Chapter")
    assert result.alignment.ends_s[-1] == 5.619
    assert result.duration_ms == 5619  # round(last character_end_time * 1000)
    assert result.character_cost == 79  # from the header, an int
    assert result.attempts == 1
    assert result.request_id == "req-123"
    assert result.model_id == "eleven_multilingual_v2"
    assert result.normalized_alignment is not None
    assert len(result.normalized_alignment.characters) == 81  # "7:30 p.m." expanded
    assert route.call_count == 1


async def test_request_body_and_headers_follow_the_contract(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(return_value=ok_response())

    await synthesize(tts, previous_text="Before.", next_text="After.")

    request = route.calls.last.request
    assert request.headers["xi-api-key"] == API_KEY
    assert request.url.params["output_format"] == "mp3_44100_128"
    body = json.loads(request.content)
    assert body["text"] == TEXT
    assert body["model_id"] == "eleven_multilingual_v2"
    assert body["voice_settings"] == VOICE_SETTINGS
    assert body["previous_text"] == "Before."
    assert body["next_text"] == "After."
    assert body["apply_text_normalization"] == "auto"


async def test_context_fields_are_omitted_when_not_given(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(return_value=ok_response())

    await synthesize(tts)

    body = json.loads(route.calls.last.request.content)
    assert "previous_text" not in body
    assert "next_text" not in body


async def test_result_is_immutable(tts: TtsClient, api: respx.MockRouter) -> None:
    api.post(path__regex=TTS_PATH).mock(return_value=ok_response())

    result = await synthesize(tts)

    with pytest.raises(AttributeError):
        result.character_cost = 1  # type: ignore[misc]


# ---------------------------------------------------------------- retries


async def test_429_then_200_retries_once_with_backoff(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(
        side_effect=[error_response(429, "rate_limit_exceeded"), ok_response()]
    )

    result = await synthesize(tts)

    assert result.character_cost == 79
    assert route.call_count == 2
    assert sleep.delays == [0.5]  # first backoff step, no Retry-After header


async def test_retry_after_header_overrides_the_backoff(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(429, "rate_limit_exceeded", **{"Retry-After": "7"}),
            ok_response(),
        ]
    )

    await synthesize(tts)

    assert sleep.delays == [7.0]


async def test_backoff_grows_exponentially_between_attempts(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(503, "server_error"),
            error_response(503, "server_error"),
            ok_response(),
        ]
    )

    await synthesize(tts)

    assert sleep.delays == [0.5, 1.0]  # base * 2**n, deterministic (no jitter), computed not timed


async def test_5xx_three_times_gives_up_with_retryable_error(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(return_value=error_response(503, "server_error"))

    with pytest.raises(RetryableError) as info:
        await synthesize(tts)

    assert route.call_count == 3  # max_attempts, never endless
    assert info.value.status == 503
    assert info.value.attempts == 3
    assert sleep.delays == [0.5, 1.0]  # no sleep after the final attempt


@pytest.mark.parametrize(
    "exc",
    [httpx.ReadTimeout("slow"), httpx.ReadError("reset"), httpx.RemoteProtocolError("eof")],
    ids=["read-timeout", "read-error", "remote-protocol"],
)
async def test_read_side_transport_errors_are_possibly_billed_and_not_retried(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep, exc: httpx.TransportError
) -> None:
    """The body was sent; the server may have synthesised and billed. A silent retry could
    double-charge (R7), so the adapter stops and the job retries with a new ledger attempt."""
    route = api.post(path__regex=TTS_PATH).mock(side_effect=exc)

    with pytest.raises(PossiblyBilled) as info:
        await synthesize(tts)

    assert route.call_count == 1
    assert sleep.delays == []
    assert info.value.status is None
    assert info.value.attempts == 1
    assert info.value.__cause__ is exc  # cause chained, not swallowed
    assert not isinstance(info.value, RetryableError)


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("slow handshake"),
        httpx.PoolTimeout("pool busy"),
        httpx.WriteTimeout("slow upload"),
    ],
    ids=["connect-error", "connect-timeout", "pool-timeout", "write-timeout"],
)
async def test_pre_send_transport_errors_are_retried_and_bounded(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep, exc: httpx.TransportError
) -> None:
    """The request never reached the server, so nothing was billed: retry up to max_attempts."""
    route = api.post(path__regex=TTS_PATH).mock(side_effect=exc)

    with pytest.raises(RetryableError) as info:
        await synthesize(tts)

    assert route.call_count == 3
    assert info.value.status is None
    assert isinstance(info.value.__cause__, type(exc))
    assert sleep.delays == [0.5, 1.0]


async def test_connection_error_then_success(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(
        side_effect=[httpx.ConnectError("refused"), ok_response()]
    )

    result = await synthesize(tts)

    assert result.character_cost == 79
    assert route.call_count == 2


# ---------------------------------------------------------------- concurrent_limit_exceeded


async def test_concurrent_limit_waits_without_consuming_attempts(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(429, "concurrent_limit_exceeded"),
            error_response(429, "concurrent_limit_exceeded"),
            error_response(503, "server_error"),
            error_response(503, "server_error"),
            ok_response(),  # third real attempt
        ]
    )

    result = await synthesize(tts)

    assert result.character_cost == 79
    assert route.call_count == 5
    assert len(sleep.delays) == 4  # two concurrency waits + two backoffs


async def test_concurrent_limit_wait_is_bounded(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(
        return_value=error_response(429, "concurrent_limit_exceeded")
    )

    with pytest.raises(RateLimited) as info:
        await synthesize(tts)

    assert route.call_count == 4  # 1 + max_concurrency_waits (3)
    assert len(sleep.delays) == 3
    assert info.value.code == "concurrent_limit_exceeded"


# ---------------------------------------------------------------- non-retryable


async def test_402_paid_plan_required_is_not_retried(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    body = fixture("error.402-paid-plan-required.json")
    route = api.post(path__regex=TTS_PATH).mock(return_value=httpx.Response(402, json=body))

    with pytest.raises(PlanRequired) as info:
        await synthesize(tts)

    assert route.call_count == 1
    assert sleep.delays == []
    assert info.value.status == 402
    assert info.value.code == "paid_plan_required"
    assert "library voices" in info.value.message
    assert isinstance(info.value, NonRetryableError)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_are_not_retried(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep, status: int
) -> None:
    route = api.post(path__regex=TTS_PATH).mock(
        return_value=error_response(status, f"error_{status}")
    )

    with pytest.raises(NonRetryableError) as info:
        await synthesize(tts)

    assert route.call_count == 1
    assert sleep.delays == []
    assert info.value.status == status
    assert info.value.code == f"error_{status}"


async def test_non_json_error_body_falls_back_to_status(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(401, text="<html>unauthorized</html>")
    )

    with pytest.raises(NonRetryableError) as info:
        await synthesize(tts)

    assert info.value.status == 401
    assert info.value.code == "http_401"


async def test_malformed_success_body_is_not_retried(tts: TtsClient, api: respx.MockRouter) -> None:
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(200, json={"unexpected": True}, headers={"character-cost": "1"})
    )

    with pytest.raises(ElevenLabsError) as info:
        await synthesize(tts)

    assert not isinstance(info.value, RetryableError)  # re-sending would cost credits again


# ---------------------------------------------------------------- the key never leaks


async def test_api_key_appears_only_in_the_request_header(
    tts: TtsClient, api: respx.MockRouter, http: httpx.AsyncClient
) -> None:
    api.post(path__regex=TTS_PATH).mock(return_value=error_response(401, "invalid_api_key"))

    with pytest.raises(ElevenLabsError) as info:
        await synthesize(tts)

    for text in (str(info.value), repr(info.value), repr(tts), repr(http)):
        assert API_KEY not in text


async def test_api_key_not_in_transport_error_message(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    api.post(path__regex=TTS_PATH).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(RetryableError) as info:
        await synthesize(tts)

    assert API_KEY not in str(info.value)
    assert API_KEY not in repr(info.value.__cause__)


# ---------------------------------------------------------------- concurrency


async def test_semaphore_limits_parallel_calls(
    http: httpx.AsyncClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    tts = TtsClient(http, concurrency=2, sleep=sleep)
    in_flight = 0
    max_in_flight = 0

    async def slow_ok(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)  # real, tiny: lets the other tasks try to enter
        in_flight -= 1
        return ok_response()

    api.post(path__regex=TTS_PATH).mock(side_effect=slow_ok)

    results = await asyncio.gather(*(synthesize(tts) for _ in range(5)))

    assert len(results) == 5
    assert max_in_flight == 2


async def test_semaphore_covers_the_whole_retry_loop(
    http: httpx.AsyncClient, api: respx.MockRouter
) -> None:
    """A call that is sleeping between attempts still holds its slot: otherwise N retrying
    calls plus N new calls would exceed the plan's concurrency the moment they wake up.
    Observed from inside the injected sleep: with limit 1, the semaphore must still be locked."""
    released_during_backoff: list[bool] = []
    tts: TtsClient

    async def observing_sleep(seconds: float) -> None:
        released_during_backoff.append(not tts.semaphore.locked())

    tts = TtsClient(http, concurrency=1, sleep=observing_sleep, max_attempts=2)
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[error_response(503, "server_error"), ok_response()]
    )

    await synthesize(tts)

    assert released_during_backoff == [False]


# ---------------------------------------------------------------- client construction


def test_build_client_sets_base_url_key_header_and_explicit_timeouts() -> None:
    client = build_client(API_KEY, base_url=BASE_URL)

    assert str(client.base_url).rstrip("/") == BASE_URL
    assert client.headers["xi-api-key"] == API_KEY
    timeout = client.timeout
    assert timeout.connect is not None and timeout.connect <= 10
    assert timeout.read is not None and timeout.read >= 30  # synthesis takes seconds
    assert timeout.write is not None and timeout.pool is not None
    assert API_KEY not in repr(client)


# ---------------------------------------------------------------- review-driven cases


async def test_missing_cost_header_yields_none_not_an_estimate(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    body = fixture("tts-with-timestamps.v2.json")
    api.post(path__regex=TTS_PATH).mock(return_value=httpx.Response(200, json=body))

    result = await synthesize(tts)

    assert result.character_cost is None  # the ledger decides, never len(text) dressed as a fact


async def test_non_integer_cost_header_is_unexpected_response(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    body = fixture("tts-with-timestamps.v2.json")
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(200, json=body, headers={"character-cost": "many"})
    )

    with pytest.raises(NonRetryableError) as info:
        await synthesize(tts)

    assert info.value.status == 200


async def test_alignment_arrays_of_different_length_are_unexpected_response(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    body = fixture("tts-with-timestamps.v2.json")
    body["alignment"]["character_end_times_seconds"] = body["alignment"][
        "character_end_times_seconds"
    ][:-1]
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(200, json=body, headers={"character-cost": "79"})
    )

    with pytest.raises(NonRetryableError) as info:
        await synthesize(tts)

    assert info.value.status == 200
    assert "length" in info.value.message


async def test_invalid_base64_audio_is_unexpected_response(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    body = fixture("tts-with-timestamps.v2.json")
    body["audio_base64"] = "not*base64!"
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(200, json=body, headers={"character-cost": "79"})
    )

    with pytest.raises(NonRetryableError):
        await synthesize(tts)


async def test_unparseable_retry_after_falls_back_to_backoff(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(
                429, "rate_limit_exceeded", **{"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
            ),
            ok_response(),
        ]
    )

    await synthesize(tts)

    assert sleep.delays == [0.5]


async def test_retry_after_is_capped(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(429, "rate_limit_exceeded", **{"Retry-After": "3600"}),
            ok_response(),
        ]
    )

    await synthesize(tts)

    assert sleep.delays == [30.0]  # never pin a slot and a job for an hour


async def test_retry_after_on_concurrency_wait_is_honoured(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[
            error_response(429, "concurrent_limit_exceeded", **{"Retry-After": "2"}),
            ok_response(),
        ]
    )

    result = await synthesize(tts)

    assert sleep.delays == [2.0]
    assert result.attempts == 1  # the wait was not an attempt


@pytest.mark.parametrize("code", ["too_many_concurrent_requests", "system_busy"])
async def test_older_concurrency_codes_are_waits_too(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep, code: str
) -> None:
    api.post(path__regex=TTS_PATH).mock(side_effect=[error_response(429, code), ok_response()])

    result = await synthesize(tts)

    assert sleep.delays == [1.0]
    assert result.attempts == 1


async def test_402_with_another_code_is_non_retryable_but_not_plan_required(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    api.post(path__regex=TTS_PATH).mock(return_value=error_response(402, "quota_exceeded"))

    with pytest.raises(NonRetryableError) as info:
        await synthesize(tts)

    assert not isinstance(info.value, PlanRequired)
    assert info.value.code == "quota_exceeded"


async def test_attempts_counts_real_requests(
    tts: TtsClient, api: respx.MockRouter, sleep: FakeSleep
) -> None:
    api.post(path__regex=TTS_PATH).mock(
        side_effect=[error_response(503, "server_error"), ok_response()]
    )

    result = await synthesize(tts)

    assert result.attempts == 2


async def test_logs_never_contain_the_key_or_the_manuscript(
    tts: TtsClient, api: respx.MockRouter
) -> None:
    import structlog.testing

    api.post(path__regex=TTS_PATH).mock(return_value=error_response(503, "server_error"))

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(RetryableError):
            await synthesize(tts)

    assert logs, "retries should be logged"
    rendered = repr(logs)
    assert API_KEY not in rendered
    assert TEXT not in rendered
    assert "Zyphora" not in rendered  # no fragment of the manuscript either


def test_from_settings_reads_the_retry_policy(http: httpx.AsyncClient) -> None:
    from retake.config import get_settings

    tts = TtsClient.from_settings(http, get_settings())

    assert tts.semaphore._value == get_settings().generation_concurrency


def test_invalid_policy_values_are_rejected(http: httpx.AsyncClient) -> None:
    with pytest.raises(ValueError):
        TtsClient(http, concurrency=0, max_attempts=3, max_concurrency_waits=1)
    with pytest.raises(ValueError):
        TtsClient(http, concurrency=1, max_attempts=0, max_concurrency_waits=1)
