# Three wrong assumptions, fixed for 780 characters of API quota

Date: 2026-09-17 · Area: infra | python

## Initial mental model
The ElevenLabs notes were written from docs and a research report, and the design followed them:
1. `GET /v1/user/subscription` would gate the budget check (R21): read `character_count`,
   refuse to generate if the batch would exceed the limit.
2. Scribe bills audio hours in dollars, so the ledger needs a `unit` column (characters vs
   audio milliseconds) and a migration before the STT adapter.
3. Scribe "normalises" mispronounced names back to their dictionary spelling, so substitution
   findings would be invisible and had to be low-confidence by design (R13).

## What failed
Two runs of `infra/verify-elevenlabs.sh` (8 TTS requests, 2 Scribe requests, 780 characters
of quota in total) contradicted all three:
1. `character_count` read 1 before and 0 after 390 billed characters; on the second run 390
   before and 390 after another 390. The counter is not consistent on the timescale of a batch.
   A gate built on it would let batches through or block them at random.
2. The Scribe response carries a `character-cost` header in the same credit unit as TTS:
   `6` for a 5.62-second clip, `7` with one keyterm (+20 %, rounded). No second unit exists.
3. Scribe did not normalise the invented name; it re-spelled it phonetically: "Zyphora" became
   "Zefora" (`logprob` −0.19) without keyterms and "Zyphora" (−0.0002) with `keyterms=Zyphora`.
   The failure mode is real but different, and it is fixable at request time.

Also found: `character-cost == len(text)` in every request (spaces and punctuation count, the
normalised text does not), no minimum charge, no format multiplier, `eleven_v3` returns
timestamps at the same price, and library voices give `402 paid_plan_required` on Free.

## Correct model
Documentation describes fields; only a request describes behaviour. For every external service
the adapter depends on, run the cheapest possible request set before designing around the docs,
and record the responses as contract fixtures. Consequences applied: the budget check is local
(`ELEVENLABS_MONTHLY_BUDGET` minus ledger credits incl. pending reservations), the subscription
API is a plausibility check at most; `ledger_entries.credits` stays a single integer for both
kinds, no migration; keyterms are a mandatory pipeline step (names extracted at import), and
`exp(logprob)` is a usable 0–1 confidence for findings.

## Decision applied
Commit "docs: verify ElevenLabs API contract (docs + live runs); add verification script":
`docs/ELEVENLABS.md` impact points 2, 7, 7b and 12; `infra/verify-elevenlabs.sh` with
`all|tts|scribe` modes; `apps/api/tests/fixtures/elevenlabs/` as respx fixtures for weeks 2 and 4.
Saved: one migration, one remote call in the hot path of every generation, and a wrong
assumption about detection.

## Interview explanation
Before writing the ElevenLabs adapter I spent 780 characters of quota on ten real requests and
found three design assumptions wrong: the quota counter cannot gate a budget, transcription cost
comes in the same unit as synthesis, and the transcriber re-spells names rather than correcting
them. The runs are a script in the repo and the responses are the contract fixtures the tests
mock. Reading the docs told me the shape of the API; only calling it told me how it behaves.
