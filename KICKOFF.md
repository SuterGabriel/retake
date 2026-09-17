# Kickoff — how to start with Claude Code

Do these by hand first (10 minutes):

1. Copy this scaffold into your cloned `retake` repo, commit as "chore: scaffold".
2. Install: `uv`, Node 22, Docker, `jq` (hooks use it), `pre-commit`; run `pre-commit install`.
3. Enable GitHub Push Protection in repo settings (Security → Secret scanning).
4. Put the two Perplexity reports into `docs/research/`.
5. Drop a public-domain chapter into `fixtures/chapter-clean.txt`.
6. Windows: run Claude Code from Git Bash so the hooks (bash + jq) work; PowerShell is not covered by the guard hook.
7. Check the Claude Code docs once for the current hooks/skills/rules format (https://code.claude.com/docs) — verify `.claude/settings.json` and the frontmatter in `.claude/rules/*.md` and `.claude/skills/*/SKILL.md` still match. This changes fast.

Then open Claude Code in the repo and paste the first prompt:

---

Read CLAUDE.md, docs/PROJECT.md, docs/REQUIREMENTS.md, docs/ARCHITECTURE.md and docs/ROADMAP.md. Confirm in five sentences what we are building, what is out of scope, and what the learning contract requires of you.

Then start Week 1, task 1: initialise `apps/api` with uv (Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg, Alembic, arq, httpx, pydantic-settings, structlog; dev: pytest, pytest-asyncio, respx, ruff, mypy strict) and `apps/web` with Vite + React 19 + TypeScript + Vitest + ESLint + Prettier. Before writing anything, explain the uv/pyproject model to me as a TypeScript developer and wait for my go.

---

Suggested sequence of prompts for week 1 after that:

- "Task 2: Dockerfiles for api and web so `make dev` works. Explain multi-stage builds briefly first."
- "Task 3: SQLAlchemy models and first Alembic migration for the five tables in docs/ARCHITECTURE.md. Explain async sessions vs. a TS ORM before implementing."
- "Task 4: TDD `domain/segmentation.py`. Write the failing tests first, show them to me, then implement."
- "Task 5: `POST /projects` and `POST /projects/{id}/import`. Routers thin, service in between."
- "/adr for arq vs Celery — I have read both docs, here is my decision: …"
- "/learning-log" after the first thing that surprised you.
- "Use the python-reviewer agent on everything in apps/api before I open the PR."

Working rhythm: one task per session, commit per task, PR per week, CI green before merge. Explain-before-implement is not optional; if Claude skips it, say "learning contract".
