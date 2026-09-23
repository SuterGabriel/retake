# 0005: Take cache keyed by content_hash

## Status
Proposed

## Context and problem
Generating a sentence costs credits (one per character). The same sentence is generated more
than once in normal use: a retried job, an import of a chapter that was imported before, or
the same sentence in two projects with the same voice. ElevenLabs bills every call, so the
service needs a way to recognise "this audio already exists" before calling the API, and the
ledger needs to show that the saving happened.

## Decision drivers
- Never pay twice for audio we already have (R21, credit visibility)
- The identity of a request must include everything that changes the audio, including the
  neighbouring text the model conditions on (`previous_text`, `next_text`)
- A cache hit must be visible in the ledger, not silent (hard rule 2)
- A cache hit must never fail with "budget exceeded": it costs nothing

## Considered options
- **A. content_hash on the take, looked up before reserve().** SHA-256 over the six inputs
  (`text`, `voice_id`, `model_id`, `voice_settings`, `previous_text`, `next_text`), canonical
  JSON so key order does not matter. Any done take with the same hash, in any project, is a
  source. The hit is a new take row pointing at the source's `audio_key`, plus a ledger row of
  kind `cache_hit` with `credits = 0` and `estimated_credits = len(text)`.
- **B. No cache; rely on ElevenLabs' own free regenerations.** Studio grants two free
  regenerations per unchanged paragraph, but that is a Studio feature, not an API contract,
  and it does not cover a re-import or a second project.
- **C. Cache keyed by `(segment_id, segment_version)` only.** Simpler, but misses the two
  cheapest wins (same sentence in another project, a re-import) and would serve stale audio
  when a neighbour's text changes, because the neighbour is not part of the key.

## Decision
We choose **A**. `domain/cache_key.py` owns the hash (pure function), `services/generation.py`
looks it up as step 3 of `generate_take`, after the per-attempt check and before the ledger
reservation. `LedgerService.record_free` writes the `cache_hit` row without touching the
budget lock.

## Consequences
- Good: a re-import or a second project with the same voice costs nothing for unchanged
  sentences; the ledger shows what it would have cost, so the saving is measurable.
- Good: a neighbour edit invalidates the cache automatically, because the neighbour text is
  in the hash (`test_changed_next_text_misses_the_cache`).
- Bad: **a deliberate retake with unchanged inputs is a cache hit and returns the same
  audio.** TTS is not deterministic; a user who dislikes a take and asks for another one wants
  different audio. Week 7 must add a `variant` (or seed) dimension to the hash so a retake is
  a cache miss on purpose; until then the API has no way to force a fresh generation. This
  was found by two contradictory tests in task 8, see the learning log of 2026-09-23.
- Bad: takes in different projects share one physical `audio_key`. Deleting a project's audio
  (week 8 cleanup) needs reference counting or a copy-on-reuse; decided then.
- Known gap: the cache path bypasses the "an attempt is a fact" rule of the ledger when a
  pending `tts:` entry exists for the same attempt. Closed in week 3 by
  `test_parallel_same_attempt_returns_409`.

## Confirmation
`tests/domain/test_cache_key.py` (every field is part of the identity; `None` and `""`
differ), `tests/services/test_generation.py::test_identical_request_reuses_audio_without_an_api_call`
(no second API call, `cache_hit` row with credits 0) and
`test_cache_hit_across_projects_with_same_voice_and_context`;
`tests/services/test_ledger.py::test_record_free_writes_a_done_entry_without_touching_the_budget`.

## Interview explanation
Every generation request has an identity: a hash over the text, the voice, the model, the
settings and the two neighbouring sentences, because the model conditions on them. Before
paying, the service looks for a finished take with the same hash and reuses its audio, and the
ledger records the hit with zero credits next to what it would have cost. The catch I found
through the tests is that a deliberate retake needs a way to opt out, which is a small extra
dimension in the hash planned for week 7.
