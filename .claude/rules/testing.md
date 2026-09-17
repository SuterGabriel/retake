---
paths:
  - "**/tests/**"
  - "**/*.test.ts"
  - "**/*.test.tsx"
---

# Testing rules

- Test observable behaviour, not private implementation.
- Every bug fix starts with a failing test that reproduces it.
- Repository/integration tests run against the real PostgreSQL and Redis from compose; do not mock the ORM.
- HTTP to ElevenLabs is mocked with `respx`. Real calls only under `@pytest.mark.external` (skipped by default).
- Fixtures: public-domain text only (`fixtures/`), synthetic WAV files generated in the test.
- Tests are order-independent and leave no state behind.
