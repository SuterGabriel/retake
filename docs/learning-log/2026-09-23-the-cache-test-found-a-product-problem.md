# The cache test found a product problem

Date: 2026-09-23 · Area: python

## Initial mental model
A cache is a pure optimisation: same inputs, same output, so serving the stored result is
always correct and never changes behaviour. That holds for a memoised function in TypeScript
and I carried it over to `content_hash` without thinking about what "same output" means for
TTS.

## What failed
Two tests in `tests/services/test_generation.py` had the same setup (one segment, unchanged
inputs, attempt 1 then attempt 2) and contradictory assertions:

- `test_identical_request_reuses_audio_without_an_api_call`:
  `cached.audio_key == original.audio_key`, `route.call_count == 1`
- `test_second_done_take_is_not_activated_automatically`:
  `second.audio_key != first.audio_key`

Both could not pass. The second test was written from the product's point of view (R18: the
user chooses between takes); the first from the ledger's. Neither was wrong.

## Correct model
TTS is not a function. The same request returns different audio each time, and that is the
product feature: a "retake" of a sentence the user dislikes only makes sense if the new take
sounds different. A content-addressed cache turns every unchanged retake into a copy of the
take the user just rejected. The cache is correct for re-imports, retried jobs and shared
sentences across projects, but it must not be the only path for the same segment. The
identity of a request therefore needs one input the manuscript does not contain: the user's
intent to hear another variant.

## Decision applied
- Assertion removed, TODO with test name left in place; ADR-0005 documents the cache and names
  the consequence. Week 7 adds a `variant` dimension to `content_hash` so a deliberate retake
  is a cache miss on purpose. Commit `1f58c51`.
- Rule for myself: when two tests contradict each other, do not pick the one that is easier to
  satisfy; ask what each test knows that the other does not.

## Interview explanation
I built a cache keyed by a hash of everything that shapes the audio, and it worked until two
of my own tests disagreed about whether a second attempt on the same sentence should return
the same audio. The disagreement was the product speaking: TTS is non-deterministic, and a
retake is a request for a different result, not a replay. The fix is a variant dimension in
the key, and the lesson is that contradictory tests are a design signal, not a test bug.
