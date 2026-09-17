# 0002: Next.js (App Router) instead of Vite + React for the front end

## Status
Accepted (2026-09-17)

## Context and problem
Retake's front end is a client-side review tool that talks to one API (FastAPI). Technically a
Vite + React single-page app is sufficient and was scaffolded first (week 1, task 1). The
project is also a portfolio for a specific target team, and that team builds its product UI
with Next.js (React, TypeScript) on top of Python services. The framework choice therefore
affects how quickly a reviewer from that team can read the code.

## Decision drivers
- Readability for the target team's reviewers: conventions they use daily
- No feature needed that Vite cannot provide; the app has no server-rendered pages
- Switch cost is near zero now (no feature code yet) and grows every week after
- Keep the architecture rule "FastAPI is the only API" intact

## Considered options
- **Vite + React + React Router**: smallest tool surface, everything is a Client Component, routing
  is explicit code. Least framework to explain; unfamiliar layout for the target team.
- **Next.js, App Router**: folder-based routing, layouts, Server Components by default, and a
  built-in production server. More framework than Retake uses; the layout the target team knows.

## Decision
We choose **Next.js (App Router)** for portfolio reasons, not technical ones. Retake uses folder
routing and layouts; the review screen is a Client Component because it needs audio, keyboard
and SSE. Next.js API routes and Server Actions are not used: FastAPI stays the single API.

## Consequences
- Good: a reviewer from the target team recognises the structure immediately.
- Good: production image ships a standalone server (`output: "standalone"`), no nginx needed.
- Bad: the Server/Client Component boundary is a concept the app barely needs but must respect.
- Bad: heavier toolchain (Next compiler, generated route types) than Vite for the same UI.
- Open: `NEXT_PUBLIC_API_URL` is baked in at build time (Docker `ARG`). If one image must serve
  several environments, switch to relative `/api` paths behind a reverse proxy, or a runtime
  `env.js` written at container start. Decide when deploying (deployment-platform ADR).

## Confirmation
- `.claude/rules/frontend.md` forbids `route.ts` handlers and Server Actions; code review checks
  `apps/web/app/**` for `route.ts` and `"use server"`.
- CI `frontend` job runs `next build`; `docker compose up` serves the app on port 3000.

## Interview explanation
The app did not need Next.js; a Vite SPA against FastAPI would have been enough. I chose Next.js
because the people who will review the code use it every day, and switching cost nothing before
feature code existed. I kept the architecture honest by forbidding Next's server features so
FastAPI remains the only API.
