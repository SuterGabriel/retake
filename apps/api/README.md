# retake (API)

FastAPI + arq backend. See the repository root README and `docs/ARCHITECTURE.md`.

```bash
uv sync            # create .venv and install (uses uv.lock)
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests
uv run uvicorn retake.api.main:app --reload
```
