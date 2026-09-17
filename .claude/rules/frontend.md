---
paths:
  - "apps/web/**/*.{ts,tsx}"
---

# Frontend rules

- Feature folders under `src/features/`; shared UI in `src/components/`.
- Server state lives in TanStack Query hooks, never in component state.
- Every async view models idle / loading / success / empty / error explicitly.
- API types are generated from the backend OpenAPI schema (`npm run gen:api`); never hand-copy enums.
- Keyboard-first review UI: every action reachable by shortcut, every control has an accessible name so Playwright can select semantically.
- Long lists (segments) are virtualised.
- No business logic in components; put it in hooks or `src/lib/`.
