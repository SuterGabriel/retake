# Retryable is a statement about billing state, not transport state

Date: 2026-09-17 · Area: python | async

## Initial mental model
Transport errors are the textbook retry case. `httpx.TransportError` covers connection refused,
DNS, timeouts; none of them produced a response, so nothing happened and the adapter can try
again. The approved test list said "Timeout: retryable, bounded", and the first implementation
did exactly that: every `TransportError` → `RetryableError` → backoff → retry.

## What failed
The python-reviewer flagged it as a blocker, with 133 tests green. A `ReadTimeout` (and
`ReadError`, `RemoteProtocolError`) fires *after* the request body was fully sent. From the
server's side the request arrived, the text was synthesised and, per docs/ELEVENLABS.md, billed
by input characters. Only the answer did not make it back in time. Retrying re-sends the same
text, the server bills it again, and if the second attempt succeeds the ledger records one cost
for two charges. That violates R7 ("a retry never double-charges") silently, which is the worst
kind of violation: no test fails, the credit balance just drifts.

## Correct model
Classify transport errors by what they prove about the server, not by what they look like:
- `ConnectError`, `ConnectTimeout`, `PoolTimeout`, `WriteTimeout`, `WriteError`: the request never
  arrived. Nothing was billed. Retry with backoff, bounded by `max_attempts`.
- `ReadTimeout`, `ReadError`, `RemoteProtocolError`: the request arrived, the outcome is unknown.
  "I don't know" must be treated as "possibly charged". The adapter raises `PossiblyBilled` and
  does not retry; the job records a pending ledger entry for that attempt and retries with a new
  attempt number, so a double charge is visible in the ledger instead of hidden in a loop.
The same rule already existed for a malformed 200 (`UnexpectedResponse`, never retried); the
review showed it applies to a missing 200 too.

## Decision applied
Commit "feat(api): ElevenLabs TTS adapter with retries, backoff and concurrency limit (TDD)":
`PRE_SEND_TRANSPORT_ERRORS` in `integrations/elevenlabs/tts.py`, `PossiblyBilled` in
`errors.py`, tests for both groups (`test_read_side_transport_errors_are_possibly_billed_and_not_retried`,
`test_pre_send_transport_errors_are_retried_and_bounded`). Task 7 (`LedgerService`) gets the
matching case: pending entry per attempt, written before the request.

## Interview explanation
My adapter retried every transport error until a reviewer pointed out that a read timeout
happens after the request was sent, so the provider may already have billed it. I split
transport errors into "never arrived" (retry, free) and "arrived, outcome unknown" (stop, mark
possibly billed, let the job retry with a new ledger attempt). In a system that spends money per
request, retryable means "provably unbilled", not "no response".
