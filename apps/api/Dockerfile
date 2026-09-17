# syntax=docker/dockerfile:1
# Build context is the repository root (see compose.yml). One image serves both
# processes: `uvicorn` (API) and `arq` (worker); compose picks the command.

# ---------------------------------------------------------------- stage 1: install
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Put the venv outside /app so the dev bind-mount of ./apps/api cannot hide it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/apps/api

# Dependencies first: this layer is cached until pyproject.toml or uv.lock change.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Source second: a code change only re-runs from here.
COPY apps/api/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------- stage 2: run
FROM python:3.12-slim-bookworm AS runtime

# ffmpeg is added in week 8 (export). Keep the image minimal until then.
RUN useradd --create-home --uid 1000 app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/apps/api /app/apps/api

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/apps/api
USER app
EXPOSE 8000

CMD ["uvicorn", "retake.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
