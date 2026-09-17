# Project context

## Why this exists

Retake is a portfolio and learning project with a concrete target: a Full-Stack
Engineer role on the ElevenLabs Creative/Studio team (Python + TypeScript/React,
"0 → 1, API through to UI", high ownership). The developer is an experienced
Angular/TypeScript frontend engineer and is learning Python backend engineering
through this project.

Two goals, in this order:
1. Learn Python backend engineering properly (async, queues, persistence, API design, testing) and be able to explain every decision in an interview.
2. Ship a working, public, documented tool that solves a real ElevenLabs user problem.

## The problem (evidence-based)

Research across ElevenLabs docs, help centre, reviews, author blogs and community posts (Sept 2026) shows one consistent pain chain for long-form narration:

> A small defect (dropped word, mispronounced name, glitch at a paragraph boundary, drift in pace or accent) is only discovered by listening to the whole chapter. Fixing it means regenerating, which costs credits and time, and often ends in an external audio editor.

Authors describe roughly 90 % of a book sounding right immediately and the last 10 % eating most of the effort. ElevenLabs has addressed pieces of this (Auto-Regenerate, two free regenerations per unchanged paragraph, word-level regeneration, Generation History, pronunciation dictionaries, character casting), but nothing closes the loop as a transparent, manuscript-based QA workflow with cost visibility.

Full research notes: `docs/research/` (add the two Perplexity reports there).

## What Retake does

Retake is a **review-first QA and repair layer** for long-form AI narration:

1. Import a chapter (TXT/Markdown for MVP), split into sentences.
2. Generate audio per sentence via ElevenLabs TTS, in parallel, through a job queue.
3. Transcribe the audio (ElevenLabs Scribe) and diff it against the manuscript.
4. Surface findings (omission, repetition, substitution, long silence, truncation) on a manuscript + waveform split view.
5. "Retake" the smallest affected unit (one sentence), crossfade it in, keep the old take for A/B.
6. Track every credit spent and show what surgical regeneration saved versus regenerating the paragraph or chapter.

## What Retake is not

- Not a generic "text in, MP3 out" audiobook generator (dozens exist on GitHub).
- Not a DAW replacement.
- Not a claim that pronunciation can be judged automatically. Omissions, repetitions, silence and timing are measured automatically; pronunciation is "machine-suggested, human-approved".
- Not a criticism of ElevenLabs Studio. Framing: "what the correction loop could look like", built on their own APIs.

## Audience

Primary: the developer (learning) and engineering reviewers at ElevenLabs.
Secondary: indie authors producing audiobooks with ElevenLabs Studio.

## Success criteria

- Public, running demo with a 2-minute video: import → 3 planted defects found → one retake → savings shown.
- Measured recall/precision on a planted-defect fixture; credits per accepted minute; savings ratio.
- `docs/adr/` with real decisions, `docs/learning-log/` with real mistakes, README a reviewer can understand in 3 minutes.
- Every file explainable by the developer without notes.

## Language

Code, docs, commits and README in English (public repo, international reviewers). Learning-log entries may start in German and be translated before publishing.
