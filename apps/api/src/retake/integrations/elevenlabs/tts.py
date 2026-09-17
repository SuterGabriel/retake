"""Text-to-speech with character timestamps (docs/ELEVENLABS.md, all items "verified (live)").

`TtsClient.synthesize` is the only way the code base generates audio. It owns retries, backoff
and the per-process concurrency limit; it knows nothing about the ledger (services/ledger.py,
task 7) or the database.
"""

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from retake.config import Settings, get_settings
from retake.integrations.elevenlabs.errors import (
    CONCURRENCY_WAIT_CODES,
    ElevenLabsError,
    PossiblyBilled,
    RateLimited,
    RetryableError,
    UnexpectedResponse,
    error_from_response,
)

log = structlog.get_logger(__name__)

SleepFn = Callable[[float], Awaitable[None]]

DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
BACKOFF_BASE_S = 0.5
CONCURRENCY_WAIT_S = 1.0
# A Retry-After longer than this would pin a semaphore slot and an arq job for that long;
# we wait at most this and let the next attempt (or the job retry) take it from there.
MAX_RETRY_AFTER_S = 30.0

# Transport errors that prove the request never reached the server: retrying cannot bill twice.
# Every other TransportError (ReadTimeout, ReadError, RemoteProtocolError) happens after the body
# was sent: the server may have synthesised and billed, so those become PossiblyBilled.
# Note: httpx's `read` timeout is per socket read, not a deadline for the whole response; a
# body that trickles in slowly can exceed it in total. Fine for single sentences, revisit if
# segments ever grow (a total deadline would be `asyncio.timeout` around the post).
PRE_SEND_TRANSPORT_ERRORS: tuple[type[httpx.TransportError], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.WriteTimeout,
    httpx.WriteError,
)


@dataclass(frozen=True, slots=True)
class Alignment:
    """Per-character timing. Covers exactly the text it belongs to (input or normalised)."""

    characters: tuple[str, ...]
    starts_s: tuple[float, ...]
    ends_s: tuple[float, ...]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Alignment":
        chars = data["characters"]
        starts = data["character_start_times_seconds"]
        ends = data["character_end_times_seconds"]
        if not (len(chars) == len(starts) == len(ends)):
            raise ValueError("alignment arrays have different lengths")
        return cls(tuple(chars), tuple(float(s) for s in starts), tuple(float(e) for e in ends))


@dataclass(frozen=True, slots=True)
class TtsResult:
    audio: bytes
    alignment: Alignment
    normalized_alignment: Alignment | None
    duration_ms: int  # from the last character end time; TTS returns no duration field
    # The `character-cost` header (an integer, hard rule 7). None if the API did not send it:
    # the ledger decides what to do with an unknown cost, never this adapter (impact point 1).
    character_cost: int | None
    request_id: str | None
    model_id: str
    attempts: int  # HTTP requests actually sent for this result (retries included)


class TtsClient:
    """One instance per process, sharing one `httpx.AsyncClient`.

    `semaphore` wraps the *whole* retry loop of a call, so a call sleeping between attempts still
    holds its slot; otherwise retrying calls plus new calls would exceed the plan's concurrency
    the moment they wake up. `sleep` is injectable so tests assert delays, not wall time.

    `max_attempts` / `max_concurrency_waits` default to the settings when not given
    (`from_settings` is the explicit form for production wiring).
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        concurrency: int,
        sleep: SleepFn = asyncio.sleep,
        max_attempts: int | None = None,
        max_concurrency_waits: int | None = None,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
    ) -> None:
        if max_attempts is None or max_concurrency_waits is None:
            settings = get_settings()
            max_attempts = (
                settings.elevenlabs_max_attempts if max_attempts is None else max_attempts
            )
            max_concurrency_waits = (
                settings.elevenlabs_max_concurrency_waits
                if max_concurrency_waits is None
                else max_concurrency_waits
            )
        if max_attempts < 1 or max_concurrency_waits < 0 or concurrency < 1:
            raise ValueError("max_attempts >= 1, max_concurrency_waits >= 0, concurrency >= 1")
        self._http = http
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._max_concurrency_waits = max_concurrency_waits
        self._output_format = output_format
        self._concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)

    @classmethod
    def from_settings(cls, http: httpx.AsyncClient, settings: Settings) -> "TtsClient":
        return cls(
            http,
            concurrency=settings.generation_concurrency,
            max_attempts=settings.elevenlabs_max_attempts,
            max_concurrency_waits=settings.elevenlabs_max_concurrency_waits,
        )

    def __repr__(self) -> str:  # never includes headers or the key
        return (
            f"TtsClient(host={self._http.base_url.host!r}, concurrency={self._concurrency}, "
            f"max_attempts={self._max_attempts})"
        )

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str,
        model_id: str,
        voice_settings: dict[str, Any],
        previous_text: str | None = None,
        next_text: str | None = None,
    ) -> TtsResult:
        body: dict[str, Any] = {
            "text": text,
            "model_id": model_id,
            "voice_settings": voice_settings,
            "apply_text_normalization": "auto",
        }
        if previous_text is not None:
            body["previous_text"] = previous_text
        if next_text is not None:
            body["next_text"] = next_text

        async with self.semaphore:
            response, attempts = await self._post_with_retries(voice_id, body)
        return self._parse(response, model_id=model_id, attempts=attempts)

    async def _post_with_retries(
        self, voice_id: str, body: dict[str, Any]
    ) -> tuple[httpx.Response, int]:
        url = f"/v1/text-to-speech/{voice_id}/with-timestamps"
        attempts = 0
        concurrency_waits = 0
        while True:
            attempts += 1
            try:
                response = await self._http.post(
                    url, params={"output_format": self._output_format}, json=body
                )
            except httpx.TransportError as exc:
                if not isinstance(exc, PRE_SEND_TRANSPORT_ERRORS):
                    # Sent, but no answer: the server may have billed. The job decides.
                    log.warning(
                        "elevenlabs.tts.possibly_billed",
                        reason=type(exc).__name__,
                        attempt=attempts,
                    )
                    raise PossiblyBilled(
                        f"no response after sending: {type(exc).__name__}: {exc}",
                        attempts=attempts,
                    ) from exc
                # Never reached the server: nothing was billed, safe to retry.
                transport_error = RetryableError(
                    f"transport error: {type(exc).__name__}: {exc}", attempts=attempts
                )
                if attempts >= self._max_attempts:
                    raise transport_error from exc
                log.warning("elevenlabs.tts.retry", reason=type(exc).__name__, attempt=attempts)
                await self._sleep(_backoff_s(attempts))
                continue

            if response.is_success:
                return response, attempts

            error = error_from_response(response, attempts=attempts)
            log.warning(
                "elevenlabs.tts.error",
                status=error.status,
                code=error.code,
                request_id=error.request_id,
                attempt=attempts,
            )
            retry_after = _capped_retry_after(error)
            if isinstance(error, RateLimited) and error.code in CONCURRENCY_WAIT_CODES:
                # The plan's slots are busy elsewhere. Waiting is not an attempt, but bounded.
                attempts -= 1
                concurrency_waits += 1
                if concurrency_waits > self._max_concurrency_waits:
                    raise error
                await self._sleep(retry_after if retry_after is not None else CONCURRENCY_WAIT_S)
                continue
            if not isinstance(error, RetryableError):
                raise error
            if attempts >= self._max_attempts:
                raise error
            await self._sleep(retry_after if retry_after is not None else _backoff_s(attempts))

    def _parse(self, response: httpx.Response, *, model_id: str, attempts: int) -> TtsResult:
        request_id = response.headers.get("request-id")
        try:
            body = response.json()
            alignment = Alignment.from_api(body["alignment"])
            normalized = body.get("normalized_alignment")
            normalized_alignment = Alignment.from_api(normalized) if normalized else None
            audio = base64.b64decode(body["audio_base64"], validate=True)
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise UnexpectedResponse(
                f"200 with a body that is not a with-timestamps result: {exc}",
                status=response.status_code,
                request_id=request_id,
                attempts=attempts,
            ) from exc

        cost_header = response.headers.get("character-cost")
        character_cost: int | None
        if cost_header is None:
            # Verified live: the header is always present; if it ever is not, the ledger must
            # know the cost is unknown rather than get an estimate dressed up as a fact.
            log.warning("elevenlabs.tts.cost_header_missing", request_id=request_id)
            character_cost = None
        else:
            try:
                character_cost = int(cost_header)
            except ValueError as exc:
                raise UnexpectedResponse(
                    f"character-cost header is not an integer: {cost_header!r}",
                    status=response.status_code,
                    request_id=request_id,
                    attempts=attempts,
                ) from exc

        duration_ms = round(alignment.ends_s[-1] * 1000) if alignment.ends_s else 0
        return TtsResult(
            audio=audio,
            alignment=alignment,
            normalized_alignment=normalized_alignment,
            duration_ms=duration_ms,
            character_cost=character_cost,
            request_id=request_id,
            model_id=model_id,
            attempts=attempts,
        )


def _capped_retry_after(error: ElevenLabsError) -> float | None:
    if not isinstance(error, RateLimited) or error.retry_after is None:
        return None
    return min(error.retry_after, MAX_RETRY_AFTER_S)


def _backoff_s(attempt: int) -> float:
    """0.5 s, 1 s, 2 s, ... for attempt 1, 2, 3. Deterministic on purpose so tests assert values.

    TODO(week 3): add jitter once several workers can hit 429 in lockstep.
    """
    return BACKOFF_BASE_S * 2.0 ** (attempt - 1)


__all__ = ["Alignment", "ElevenLabsError", "TtsClient", "TtsResult"]
