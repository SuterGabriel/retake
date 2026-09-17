---
paths:
  - "apps/web/**/*.{ts,tsx,mts}"
---

# Frontend rules

- Next.js App Router. Routes and layouts live under `apps/web/app/`; there is no `src/`.
- Feature folders under `apps/web/features/`; shared UI in `apps/web/components/`.
- Review-UI components are Client Components (`"use client"`): they need audio, keyboard and SSE. Layouts and static pages stay Server Components.
- No Next.js API routes (`route.ts`) and no Server Actions (`"use server"`). FastAPI is the only API; the browser calls it at `NEXT_PUBLIC_API_URL`.
- No secrets in `NEXT_PUBLIC_*`: those values are inlined into the browser bundle at build time.
- Server state lives in TanStack Query hooks, never in component state.
- Every async view models idle / loading / success / empty / error explicitly.
- API types are generated from the backend OpenAPI schema (`npm run gen:api`); never hand-copy enums.
- Keyboard-first review UI: every action reachable by shortcut, every control has an accessible name so Playwright can select semantically.
- Long lists (segments) are virtualised.
- No business logic in components; put it in hooks or `apps/web/lib/`.
