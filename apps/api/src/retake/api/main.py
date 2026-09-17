"""FastAPI application entry point. Routers are registered here; logic lives in services."""

from fastapi import FastAPI

from retake import __version__
from retake.api.errors import register_error_handlers
from retake.api.routers import projects
from retake.config import get_settings

app = FastAPI(title="Retake", version=__version__)
register_error_handlers(app)
app.include_router(projects.router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment, "version": __version__}
