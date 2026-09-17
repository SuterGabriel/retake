"""FastAPI application entry point. Routers are registered here; logic lives in services."""

from fastapi import FastAPI

from retake import __version__
from retake.config import get_settings

app = FastAPI(title="Retake", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment, "version": __version__}
