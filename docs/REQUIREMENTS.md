# Requirements

## MVP scope (v1.0) — must have

### Import
- R1. Submit chapter text (TXT/Markdown content) as a JSON body; the frontend reads the file. Max 50k characters.
- R2. Split into sentences; each sentence becomes a `Segment` with a stable position.
- R3. Preserve paragraph boundaries for later pause handling.

### Generation
- R4. Generate audio per segment through a job queue; segments run in parallel with a configurable concurrency limit.
- R5. Retry on 429/5xx with exponential backoff; honour `Retry-After`.
- R6. Every generation writes a `LedgerEntry` (credits = characters billed, as returned or computed).
- R7. A retry of the same segment version never double-charges the ledger (idempotency).
- R8. Live progress in the UI via Server-Sent Events.

### Detection
- R9. Transcribe each take with Scribe, with word timestamps.
- R10. Normalise manuscript and transcript identically (numbers to words, punctuation stripped, case-folded, common abbreviations expanded).
- R11. Word-level diff produces `Finding`s of type: `omission`, `repetition`, `substitution`, `silence` (> 2.0 s inside a sentence), `truncation` (audio much shorter than expected words-per-second).
- R12. Each finding has a time span, a confidence (0–1) and a status (`open`, `fixed`, `ignored`).
- R13. `substitution` defaults to low confidence (transcription may auto-correct names).

### Review UI
- R14. Split view: manuscript (virtualised list) left, waveform of selected segment right, findings as markers.
- R15. Keyboard workflow: `J`/`K` next/previous finding, `Space` play, `R` retake, `A`/`B` switch take, `X` ignore, `?` help.
- R16. Cost bar: credits spent this session, estimated credits saved vs paragraph regeneration.

### Retake
- R17. Regenerate one segment; creates a new `Take`; old take stays.
- R18. Only one take per segment is `active`; user can switch.
- R19. Export stitches active takes with a 20 ms crossfade, loudness-normalised to −16 LUFS, MP3.

### Non-functional
- R20. `docker compose up` starts everything; `.env.example` documents all variables. Settings load with sensible defaults for everything except the API key, so tests run without an object store.
- R21. Monthly credit budget (`ELEVENLABS_MONTHLY_BUDGET`); generation refuses to start if it would exceed it.
- R22. API key only server-side; never in responses, logs or the browser.
- R23. OpenAPI docs served at `/docs`.
- R24. CI green on every PR: ruff, mypy strict, pytest, eslint, tsc, vitest.

## Explicitly out of scope for v1.0
- EPUB/DOCX import
- Multi-speaker casting and dialogue attribution
- Pronunciation scoring, pronunciation dictionary management
- Click/pop detection
- ElevenLabs Studio API integration
- User accounts, multi-tenancy
- WebSockets (SSE is sufficient; revisit via ADR if bidirectional needs appear)

## User stories (acceptance criteria in `tests/`)
- As an author, I upload a chapter and see it split into sentences within 2 s.
- As an author, I start generation and watch progress per sentence.
- As an author, I see a list of findings sorted by position and can jump between them with the keyboard.
- As an author, I play a finding, hear the defect, press `R`, and get a new take within ~10 s.
- As an author, I compare old and new take and pick one.
- As an author, I export the chapter and get an MP3 with the chosen takes.
- As an author, I see how many credits I spent and how many I saved.

## Planted-defect fixture (for metrics)
`fixtures/chapter-clean.txt` (public domain, ~5k words) and `fixtures/chapter-defects.json` listing 20 deliberate edits applied to a copy before generation: 8 omissions, 5 repetitions, 5 substitutions, 2 truncations. Recall/precision per type are reported in `docs/METRICS.md`.
