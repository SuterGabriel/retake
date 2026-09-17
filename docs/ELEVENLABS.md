# ElevenLabs integration notes

Working notes for the adapter. Verified on **2026-09-17** against the official docs by fetching
each page; the Perplexity research of the same date was treated as a hypothesis. Status per item:

- **verified**: official page says it, URL given
- **hypothesis**: only the research or a help-centre page (not fetchable by automation, HTTP 403) says it
- **needs real API call**: docs and research disagree, or the docs are silent

Re-verify anything marked hypothesis or needs-real-API-call with `infra/verify-elevenlabs.sh`
before the week-2 adapter relies on it.

## Endpoints (v1.0)

| Item | Status | Finding | Source |
|---|---|---|---|
| TTS with timing | verified | `POST /v1/text-to-speech/{voice_id}/with-timestamps`, query `output_format` (default `mp3_44100_128`), `enable_logging`. Body: `text` (required), `model_id` (default `eleven_multilingual_v2`), `voice_settings` {stability, similarity_boost, style, speed, use_speaker_boost}, `seed`, `previous_text`/`next_text`, `previous_request_ids`/`next_request_ids`, `apply_text_normalization` (default `auto`), `language_code`, `pronunciation_dictionary_locators`. Response JSON: `audio_base64`, `alignment` and `normalized_alignment`, each with `characters`, `character_start_times_seconds`, `character_end_times_seconds`. | https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps |
| Which models support timestamps | verified (live) | `eleven_multilingual_v2` and `eleven_v3` both return `alignment`/`normalized_alignment`, same `character-cost`. | live run 2026-09-17 |
| Speech-to-Text (batch) | verified | `POST /v1/speech-to-text`, multipart. `model_id` required (`scribe_v2`), `file` (max 5 GB on the endpoint page; capability page says 3 GB / 10 h), `language_code` (ISO-639-1/3, null = auto), `timestamps_granularity` `word` \| `character`, `diarize`, `tag_audio_events`, `num_speakers` (max 32), `keyterms` (list of strings, max 1000, each < 50 chars and ≤ 5 words). Response: `language_code`, `language_probability`, `text`, `words[]` with `text`, `type` (`word` \| `spacing` \| `audio_event`), `start`, `end`, `speaker_id`, `logprob` (range [-inf, 0]), optional `characters[]`. | https://elevenlabs.io/docs/api-reference/speech-to-text/convert |
| Scribe models | verified | `scribe_v2` (batch), `scribe_v2_realtime`, `scribe_v2_medical`. `scribe_v1` is listed as deprecated/removed, use `scribe_v2`. | https://elevenlabs.io/docs/models |
| Subscription / quota | verified, **not immediately consistent** | `GET /v1/user/subscription`: `tier`, `character_count` (used), `character_limit` (period limit), `max_credit_limit_extension` (int or "unlimited"), `can_extend_character_limit`, `next_character_count_reset_unix`, `status`, `current_overage`. No "remaining" field: remaining = `character_limit - character_count`. **Live:** `character_count` was 1 before and 0 after spending 390 characters within a minute; the counter lags or is reset asynchronously. Do not use it for the budget check (impact point 12). | https://elevenlabs.io/docs/api-reference/user/subscription/get, live run |
| Forced alignment | verified (partly) | `POST /v1/forced-alignment`, multipart `file` (< 1 GB on the API page) + `text`. Response `characters[]` {text,start,end}, `words[]` {text,start,end,loss}, overall `loss`. Billing not stated on the page (research: same price as STT). Not used in v1.0, but see impact section. | https://elevenlabs.io/docs/api-reference/forced-alignment/create |
| Pronunciation dictionaries, Studio API | not used in v1.0 | | |

## Models

| Item | Status | Finding | Source |
|---|---|---|---|
| Default model | verified | `eleven_multilingual_v2`: "Most stable on long-form generations", 10,000 chars/request, 29 languages. Keep as default. | https://elevenlabs.io/docs/models |
| Expressive alternative | verified | `eleven_v3`: 5,000 chars/request, 70+ languages, listed for "Audiobook Production". Not the default (consistency over expressiveness). | same |
| Fast/cheap | verified | `eleven_flash_v2_5`: 40,000 chars, ~75 ms; `eleven_turbo_v2_5` and `eleven_turbo_v2` are **deprecated** in favour of Flash. `eleven_v3_conversational` is realtime-oriented, char limit not published. | same |
| Per-model limits at runtime | hypothesis | `GET /v1/models` returns `maximum_text_length_per_request`; prefer reading it over hard-coding. Our segments are sentences, far below any limit. | research |

## Cost model

| Item | Status | Finding | Source |
|---|---|---|---|
| TTS unit | verified | Billed per character of input text; "$0.10 per 1,000 characters (multilingual models)". Included characters: Starter 10k, Creator 220k, Pro 990k. | https://elevenlabs.io/pricing/api |
| Billed characters per request | verified | Response header **`character-cost`** carries the request's cost; `request-id` and `x-trace-id` are also headers. The JSON body has no cost field. | https://elevenlabs.io/docs/api-reference/introduction |
| What counts as a character | verified (live) | `character-cost == len(text)` in all 8 requests: every input character counts, including spaces and punctuation; the normalised text ("7:30 p.m." spelled out) does not change the cost. `previous_text`/`next_text` were not sent; still open whether they count (they are optional context, so the adapter can measure once when it first uses them). | live run 2026-09-17 |
| Minimum charge / rounding | verified (live) | None: a 1-character request costs 1. | live run 2026-09-17 |
| Output format cost | verified (live) | No effect: same text as `mp3_44100_128` and `pcm_22050` cost the same. `pcm_22050` is available on Free; 44.1 kHz PCM/WAV is Pro. | live run 2026-09-17 |
| Free regenerations | hypothesis | Help centre (403 for automation) reportedly states free regenerations exist only in the web/Studio UI, never via API. Treat every API generation as paid. | research; verify manually in help centre |
| Scribe unit | verified (docs + live) | Pricing page: per hour of audio, "$0.22 per hour (Scribe)". **Live:** the Scribe response also carries a `character-cost` header, in the same credit unit as TTS: a 5.62 s clip cost **6** without keyterms and **7** with one keyterm (+20 %, rounded). Working hypothesis: 1 credit per started second of audio. Confirm with one longer clip before relying on the per-second rule; the header value itself is what the ledger stores. Keyterms +$0.05/h (endpoint page: +20 %), entity detection +$0.07/h (+30 %). | https://elevenlabs.io/pricing/api, endpoint page, live run |
| Scribe included hours per plan | needs real API call | Research claimed Starter 27 h / Creator 100 h; the pricing page fetched today shows Starter 4.5 h / Creator 27 h. Confirm in the account UI. | |

## Behaviour to design around

| Item | Status | Finding | Source |
|---|---|---|---|
| TTS concurrency per plan | hypothesis | Research: non-Flash models Free 2 / Starter 3 / Creator 5 / Pro 10; Flash double that. The docs pages fetched today do not state per-plan numbers; help centre article is 403 for automation. Keep `GENERATION_CONCURRENCY=3` until measured. | research; verify manually |
| STT concurrency | needs real API call | Capability page: "Concurrency = min(4, round_up(audio_duration_secs/480))" per file (internal segmentation), no per-plan table. Research cites two conflicting per-plan tables (10/15/25/50 vs 8/12/20/40). | https://elevenlabs.io/docs/capabilities/speech-to-text |
| 429 handling | hypothesis | Research: `rate_limit_exceeded` → exponential backoff; `concurrent_limit_exceeded` → wait for in-flight requests; older texts name `too_many_concurrent_requests` / `system_busy`. No official errors page found (404). | research |
| 402 `paid_plan_required` | verified (live) | Library voices on Free return 402 with `detail.code = paid_plan_required`. Not retryable. See "Live findings". | live run |
| `Retry-After` | needs real API call | Not mentioned on any fetched page. Adapter: honour it if present, otherwise own backoff. Script logs the 429 headers if one occurs. | |
| Timestamps semantics | verified | `alignment` is per character of the **input** text, `normalized_alignment` per character of the normalised text (e.g. numbers spelled out). They locate characters; they do not prove they were spoken. Omission detection therefore uses the Scribe transcript, as planned. | timestamps endpoint page |
| Word confidence from Scribe | verified (live) | `words[].logprob` in [-inf, 0]; no 0–1 confidence field. Live: correct common words sit at −1e-5 … 0; the mis-heard name "Zefora" sat at −0.19, the corrected "Zyphora" (with keyterm) at −0.0002. `exp(logprob)` is a usable 0–1 confidence for R12. Keys per word entry: `end, logprob, start, text, type`. | STT endpoint page, live run |
| Names in transcripts | verified (live) | Without keyterms Scribe wrote the invented name **"Zefora"** for spoken "Zyphora"; with `keyterms=Zyphora` it wrote **"Zyphora"**. So names are re-spelled phonetically, not normalised to dictionary words, and keyterms fix it. Send character/place names as keyterms (≤ 100 to avoid the 20 s minimum). | live run |
| Transcript text shape | verified (live) | Punctuation and quotes stay attached to words (`one.`, `said,`, `"Nobody`, `name."`); numbers come back as digits (`7:30 PM` for input `7:30 p.m.`); `spacing` entries sit between words (13 spacing for 14 words). `domain.normalize` must strip punctuation/quotes and unify numbers and abbreviations on both sides. | live run |
| Extra response fields not in the docs | verified (live) | TTS: `quality_check` (object, purpose undocumented; ignore). Scribe: `audio_duration_secs` (5.62 for the test clip; the billed duration basis) and `transcription_id` (an id on the account; removed from the fixtures). | live run |
| Scribe request shape | verified (live) | Multipart with `keyterms` as a repeated form field works; `language_code=eng`, `timestamps_granularity=word`, `diarize=false`, `tag_audio_events=false`. No `speaker_id`/`characters` keys when diarisation and character granularity are off. | live run |
| Context for sentence chunks | verified | `previous_text`/`next_text` and `previous_request_ids`/`next_request_ids` improve transitions between separately generated sentences; `seed` is best-effort, not a reproducibility guarantee. | timestamps endpoint page, research |

## Impact on data model and requirements

Checked against `docs/ARCHITECTURE.md`, `docs/REQUIREMENTS.md` and `apps/api/src/retake/db/models.py`. Nothing changed in code; these are the deltas to decide in week 2.

1. **Credits as integer (rule 7) holds for TTS.** `character-cost` is an integer count of characters. `LedgerEntry.credits` stays `int`. The ledger must store the header value, never `len(text)`; `len(text)` is only the pre-flight estimate for the budget check.
2. **Superseded by the live run: no `unit` column.** The original concern was that Scribe bills in audio hours and the ledger would need a unit. Measured: the Scribe response carries `character-cost` in the same credit unit as TTS (6 credits for a 5.62 s clip, 7 with one keyterm). The live run showed a `character-cost` header on the Scribe response (6 credits for 5.6 s, 7 with a keyterm). So `ledger_entries.credits` (int) works for `kind = "stt"` unchanged: store the header value. No `unit` column needed. Keep `takes.duration_ms` as the audio fact; the per-second billing rule is a hypothesis to confirm with a longer clip, but the ledger never depends on it.
3. **New ledger columns worth adding with the adapter (migration in the same commit):** `request_id` (from the `request-id` header, for support and duplicate detection) and possibly `character_cost_reported` vs `character_cost_estimated`. Decide when writing `LedgerService`.
4. **`takes.duration_ms`** is not returned by TTS. Derive it from the last `character_end_times_seconds` of `alignment` (×1000, rounded) or from the decoded audio. The alignment value is cheaper and needs no audio decoding.
5. **R6/R7 (every generation writes a ledger entry; retries never double-charge).** Every successful request is a charge, including retries that produce audio, because API regenerations are never free. So: retry only when no usable response arrived (connection error, 429, 5xx with no body); after a 2xx never re-send. The idempotency key `f"{kind}:{segment_id}:{version}:{attempt}"` must be written *before* the request as `pending` and completed with `character-cost` afterwards, so a crash between response and commit is visible (a pending entry with no cost = "check with request-id").
6. **R21 budget check via the subscription API is advisory, not atomic.** Remaining = `character_limit - character_count`, but other workers spend between check and generation. `LedgerService.reserve()` must keep local in-flight reservations (sum of pending entries' estimates) and reconcile with the reported `character-cost` after each response. `ELEVENLABS_MONTHLY_BUDGET` remains a local cap on top.
7. **Scribe options for R9/R13.** Use `model_id=scribe_v2`, `timestamps_granularity=word` (default), `diarize=false`, `tag_audio_events=false`, `keyterms` from the project's proper nouns (cap at 100). `words[].type == "spacing"` entries must be skipped when building the word list. Finding confidence (R12, 0–1) for substitutions can be derived from `exp(logprob)` of the differing word; still default low (R13). **Live evidence for R13:** an invented name was re-spelled ("Zefora") without keyterms and fixed with one. Keyterms are therefore part of the generate/analyse pipeline, not an option: extract capitalised tokens per project (names, places) at import time.
7b. **R10 normalisation has concrete targets now.** Scribe output attaches punctuation and quotes to words and emits digits (`7:30 PM`), while the manuscript has `7:30 p.m.`. `domain.normalize` must: strip punctuation and quotes, lower-case, expand numbers/times to words or, simpler, normalise both sides to digits and a fixed abbreviation set (`p.m.` → `pm`). Decide in week 4 with the planted-defect fixture.
8. **Timestamps for findings (R12 time spans).** Word spans come from Scribe (`start`/`end` seconds → ms). TTS `alignment` is character-level on the input; map characters to words by splitting on whitespace characters in `characters`. Both are seconds as floats; convert to int milliseconds at the boundary.
9. **Forced alignment as a detection option (week 4, not v1.0 scope).** `POST /v1/forced-alignment` aligns the *manuscript* to the audio and returns a per-word `loss`; a high loss on a word is a direct omission/substitution signal without a transcript diff. Worth a spike if Scribe-based detection has low precision; billing must be verified first.
10. **Concurrency.** `GENERATION_CONCURRENCY=3` matches the researched Starter limit for non-Flash models but is unverified. The adapter should treat `concurrent_limit_exceeded` as "wait, do not count as a retry attempt" so it never burns attempts or credits.
11. **Error taxonomy for the adapter (R5).** Retry: connection errors, 429, 5xx. Never retry: 400, 401, 402 (`paid_plan_required`), 403, 404, 422. Map on `detail.code` from the error body, fall back to the HTTP status. A 402 on a project's voice should surface as a project-level finding ("voice not available on this plan"), not as a failed take that the worker keeps retrying.
12. **R21 budget check runs on the local ledger only.** The subscription counter is not immediately consistent (used=1 before, used=0 after 390 billed characters), so it cannot gate generation. Budget = `ELEVENLABS_MONTHLY_BUDGET - sum(ledger credits this period, including pending reservations)`. The subscription API is at most a coarse plausibility check (e.g. once per batch, log a warning if it disagrees by more than a threshold), never a gate. This simplifies `LedgerService.reserve()`: one source of truth, no remote call in the hot path. Supersedes the "advisory" wording in point 6.

## Live findings (first run of `infra/verify-elevenlabs.sh`, Free plan, 2026-09-17)

- **Library voices are blocked on Free via the API**: HTTP 402, `code = paid_plan_required`,
  message "Free users cannot use library voices via the API." Premade voices work. The adapter
  must treat 402 as **not retryable** (a plan problem, not a transient one).
- **Error body structure**: `{"detail": {"type", "code", "message", "status", "request_id"}}`.
  Example: `type = payment_required`, `code = paid_plan_required`, `status = payment_required`.
  The adapter's error mapping keys on `detail.code`.
- **Subscription endpoint works on Free**: `tier`, `character_count`, `character_limit`, `status`
  present as documented.
- **Billing follows the input text, not the normalised text**: confirmed over 8 requests,
  `character-cost == len(text)` every time (1, 10, 100 characters; whitespace runs count;
  `normalized_alignment` longer than the input does not change the cost). No minimum charge,
  no format multiplier, `eleven_v3` costs the same as v2 per character.
- `character-cost` and `request-id` headers are present on the 200 response as documented.
- `request-id` values seen live are 20 characters (e.g. base62), `x-trace-id` 32 hex characters;
  `request_id` columns are `String(64)` with that margin.
- **Subscription counter is not immediately consistent**: `character_count` went from 1 to 0
  while 390 characters were billed. See impact point 12.
- **Subscription counter lag confirmed on the second run**: `used=390` before and after another
  390 billed characters (headers summed to 390, quota delta 0).
- **Scribe (second run, 5.62 s clip)**: 200 on both variants; `character-cost: 6` without and
  `7` with `keyterms=Zyphora`; `logprob` present on every word; 14 words, 13 spacing entries;
  the name "Zyphora" was transcribed as "Zefora" without the keyterm and correctly with it.
- **TTS timing**: `alignment.characters` length equals `len(text)` in all 8 requests (the
  alignment covers exactly the input); last `character_end_times_seconds` gives the duration
  (5.62 s for v2, 6.64 s for v3 on the same sentence). `normalized_alignment` is longer than the
  input for v2 when text is expanded (`7:30 p.m.`), equal for v3.

## Test material

- Public-domain text only (`fixtures/chapter-clean.txt`, Project Gutenberg). Never commit generated audio of copyrighted books.
- Keep fixtures under 5k words to bound cost.

## Budget

- `ELEVENLABS_MONTHLY_BUDGET` (characters) checked before every batch, locally, plus the subscription API as a sanity check.
- Cache: identical (text, voice, model, settings) never generates twice; a segment's audio is reused across runs.
