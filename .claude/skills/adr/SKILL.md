---
name: adr
description: Create an Architecture Decision Record in docs/adr/ using the MADR-style template. Use when the developer says "/adr" or when a change affects architecture (new dependency, new infrastructure, data model shape, protocol choice).
---

# Create an ADR

1. Read `docs/adr/` to find the next number and check for related decisions.
2. Copy `docs/adr/0000-template.md` to `docs/adr/NNNN-short-kebab-title.md`.
3. Fill it in. Keep it under 60 lines. Real options only; at least two considered.
4. Status starts as `Proposed`. The developer changes it to `Accepted`.
5. In "Confirmation", name the test or check that proves the decision is honoured.
6. Add one line for the ADR to the table in `docs/adr/README.md`.
7. Do not write ADRs for trivial choices. If unsure, ask.
