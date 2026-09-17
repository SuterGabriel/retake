# ElevenLabs integration notes

Working notes for the adapter. Everything marked **VERIFY** must be checked against the current docs (https://elevenlabs.io/docs) before relying on it; the API changes often.

## Endpoints used (v1.0)
- Text-to-Speech, ideally the variant that returns word/character timestamps alongside audio — **VERIFY** exact endpoint and response shape.
- Speech-to-Text (Scribe v2) with word timestamps; `keyterms` option may help with names — **VERIFY**.
- Pronunciation dictionaries: not used in v1.0.
- Studio API: not used (access is on request).

## Cost model
- TTS is billed per character. Confirm how the API reports billed characters (response header or field) — **VERIFY**; until confirmed, `credits = len(text)` with a note.
- Free regenerations in the web UI do **not** apply to API calls. All API generations cost credits. This is why the ledger and the "smallest safe span" matter.
- Scribe has its own pricing — **VERIFY** and record in ledger with `kind = "stt"`.

## Behaviour to design around
- Rate limits (429) with `Retry-After`; concurrency limits depend on plan — **VERIFY** your plan's limit and set `GENERATION_CONCURRENCY` accordingly.
- Timestamps returned by TTS refer to the *input text*, not to what was actually spoken. They locate words; they do not prove words were spoken. Omission detection therefore uses the Scribe transcript.
- STT tends to normalise mispronounced names back to the expected spelling. Substitution findings are low-confidence by design.
- Model choice: multilingual v2 is generally reported as more consistent than v3 for long-form; v3 is more expressive. Default to v2 for the demo — **VERIFY** current model ids.
- Long inputs degrade; sentence-level generation sidesteps this.

## Test material
- Public-domain text only (e.g. Project Gutenberg). Never commit generated audio of copyrighted books.
- Keep a `fixtures/` chapter under 5k words to bound cost during development.

## Budget
- `ELEVENLABS_MONTHLY_BUDGET` (credits) checked before every batch.
- Cache: identical (text, voice, model, settings) never generates twice; a segment's audio is reused across runs.
