# Roadmap (10 weeks, part-time)

Rule: every week ends with something runnable and a learning-log entry. Narrow and finished beats broad and half-done.

## Week 0 — Before code (this weekend)
- [ ] Verify every **VERIFY** item in docs/ELEVENLABS.md against current docs; record answers there
- [ ] Create `fixtures/chapter-clean.txt` (public domain) and `fixtures/chapter-defects.json`
- [ ] Decide arq vs Celery (ADR-0001)

## Week 1 — Foundation
- [ ] Monorepo scaffold, uv + pyproject, Next.js app (App Router, TypeScript, Vitest, ESLint, Prettier), compose (postgres, redis, minio), Makefile
- [ ] CLAUDE.md, rules, hooks, pre-commit (ruff, prettier, gitleaks), CI (backend + frontend jobs)
- [ ] SQLAlchemy models + first Alembic migration for the five tables
- [ ] `POST /projects`, `POST /projects/{id}/import` with `domain.segmentation` (TDD)
- [ ] ADR-0001 arq vs Celery
- Learn: uv, pyproject, Pydantic vs dataclass, async sessions, Alembic

## Week 2 — First audio
- [ ] ElevenLabs adapter (`tts.py`) with retries, timeouts, respx contract tests
- [ ] `LedgerService` with idempotency (TDD) and budget check
- [ ] One synchronous endpoint that generates a single segment (no queue yet) — first real audio
- [ ] Docker CI job; branch ruleset
- Learn: httpx, context managers, exceptions with context, integer money

## Week 3 — Queue
- [ ] arq worker, `generate_take` job, concurrency limit, idempotent retries
- [ ] SSE endpoint publishing progress from Redis
- [ ] Worker integration tests against real Redis
- [ ] ADR-0003 SSE vs WebSockets
- Learn: arq, Redis pub/sub, idempotency keys, asyncio semantics vs Promises

## Week 4 — Detection
- [ ] Scribe adapter + contract tests
- [ ] `domain.normalize`, `domain.diff`, `domain.findings` (TDD, planted-defect fixture)
- [ ] `domain.audio_checks` (silence, truncation) on synthetic WAVs
- [ ] First recall/precision numbers in `docs/METRICS.md`
- Learn: text normalisation edge cases, Levenshtein alignment, why STT hides pronunciation errors

## Week 5 — Review UI, part 1
- [ ] OpenAPI-generated API client (first frontend code that talks to the API), project import screen, segment list (virtualised)
- [ ] Review page is a Client Component (`"use client"`): audio, keyboard and SSE need the browser
- [ ] Waveform (wavesurfer.js) with finding markers
- [ ] Playwright MCP set up; first smoke test
- Learn: consuming SSE in React, virtualisation

## Week 6 — Review UI, part 2
- [ ] Findings list, keyboard workflow (J/K/Space/R/A/B/X/?), cost bar
- [ ] Component tests for the keyboard map
- Learn: accessibility for keyboard-first UIs

## Week 7 — Retake & A/B
- [ ] `POST /segments/{id}/retake`, take activation, A/B in UI
- [ ] Savings calculation (sentence vs paragraph vs chapter) in ledger
- Learn: versioning models, optimistic updates

## Week 8 — Export (known to be tight; spike ffmpeg in week 7 if time allows)
- [ ] Spike: ffmpeg concat + acrossfade + loudnorm on two takes by hand; note sample-rate handling
- [ ] Export job (subprocess via `asyncio.create_subprocess_exec`), download
- [ ] ADR-0004 object storage, ADR-0006 deployment platform
- Learn: subprocess handling, audio basics (LUFS, crossfade)

## Week 9 — Hardening & deploy
- [ ] Deploy (one platform), health checks, structured logging
- [ ] Full planted-defect run end-to-end; final metrics
- [ ] python-reviewer pass over the whole backend; fix findings
- Learn: deployment, observability basics

## Week 10 — Presentation
- [ ] README with GIF, live link, architecture, metrics, known limits
- [ ] 2-minute demo video
- [ ] Blog post: "Finding the broken 10 % of an AI audiobook"
- [ ] Application + message to Studio team engineers

## Parking lot (v1.1+)
EPUB import · multi-speaker casting · pronunciation CI · click detection · Studio API · Text-to-Dialogue for v3
