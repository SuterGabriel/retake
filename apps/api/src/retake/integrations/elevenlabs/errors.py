"""Adapter error hierarchy. Callers catch a class, never a status code.

    ElevenLabsError                 status, code, message, request_id, attempts
    ├── RetryableError              pre-send transport errors (connect, pool, write), 429, 5xx
    │   └── RateLimited             429; carries retry_after (seconds) when the API sent one
    ├── PossiblyBilled              read-side transport errors (ReadTimeout, ReadError,
    │                               RemoteProtocolError): the request was sent, the server may
    │                               have synthesised and billed. Not retried here; the job
    │                               retries with a new ledger attempt so the cost stays visible.
    └── NonRetryableError           400, 401, 402, 403, 404, 422, malformed 200 bodies
        ├── PlanRequired            402 paid_plan_required: a plan problem, surface per project
        └── UnexpectedResponse      2xx whose body is not what the contract says; re-sending
                                    would cost credits again, so it is not retryable

"Retryable" is a statement about billing state, not transport state: a retry is only free when
the server provably did nothing.

The error body `{"detail": {"type", "code", "message", "status", "request_id"}}` (verified live,
docs/ELEVENLABS.md) is parsed in exactly one place, `error_from_response`. Nothing here ever
holds the API key: only status, code, message and ids.
"""

from typing import Any

import httpx

# 429 codes that mean "your plan's slots are busy": wait, do not count as an attempt.
# The first is the current name; the others appear in older docs (docs/ELEVENLABS.md).
CONCURRENCY_WAIT_CODES = frozenset(
    {"concurrent_limit_exceeded", "too_many_concurrent_requests", "system_busy"}
)
PAID_PLAN_CODE = "paid_plan_required"


class ElevenLabsError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.attempts = attempts

    def __str__(self) -> str:
        where = f"HTTP {self.status}" if self.status is not None else "no response"
        return (
            f"{self.code or 'elevenlabs_error'} ({where}, attempt {self.attempts}): {self.message}"
        )


class RetryableError(ElevenLabsError):
    """Worth another attempt: nothing was billed, or the API asked us to wait."""


class RateLimited(RetryableError):
    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(
            message, status=status, code=code, request_id=request_id, attempts=attempts
        )
        self.retry_after = retry_after


class PossiblyBilled(ElevenLabsError):
    """The request reached the server but no response arrived; it may have been billed.

    The adapter does not retry this. The caller (job) records a pending ledger entry for the
    attempt and retries with a new attempt number, so a double charge is visible, never silent.
    """


class NonRetryableError(ElevenLabsError):
    """Re-sending the same request cannot succeed (or would bill again)."""


class PlanRequired(NonRetryableError):
    """402 paid_plan_required: the voice or feature is not available on this plan."""


class UnexpectedResponse(NonRetryableError):
    """A 2xx whose body does not match the contract. The request was billed; do not repeat it."""


def _parse_detail(response: httpx.Response) -> dict[str, Any]:
    """The `detail` object, or {} when the body is not the documented JSON (proxies, HTML)."""
    try:
        body = response.json()
    except ValueError:
        return {}
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, dict) else {}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` as seconds; HTTP-date form is not supported (not seen from this API)."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def error_from_response(response: httpx.Response, *, attempts: int) -> ElevenLabsError:
    """Translate a non-2xx response into the matching exception (does not raise)."""
    status = response.status_code
    detail = _parse_detail(response)
    code = str(detail.get("code") or f"http_{status}")
    message = str(detail.get("message") or response.reason_phrase or f"HTTP {status}")
    request_id = detail.get("request_id") or response.headers.get("request-id")
    common: dict[str, Any] = {
        "status": status,
        "code": code,
        "request_id": request_id,
        "attempts": attempts,
    }
    if status == 429:
        return RateLimited(message, retry_after=_retry_after_seconds(response), **common)
    if status >= 500:
        return RetryableError(message, **common)
    if status == 402 and code == PAID_PLAN_CODE:
        return PlanRequired(message, **common)
    return NonRetryableError(message, **common)
