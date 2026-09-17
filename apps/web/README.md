# web

Next.js (App Router) front end for Retake. Talks only to the FastAPI backend at
`NEXT_PUBLIC_API_URL`; no Next.js API routes, no Server Actions (see ADR-0002).

```bash
npm ci
npm run dev          # http://localhost:3000
npm run lint && npm run typecheck && npm test -- --run && npm run build
```
