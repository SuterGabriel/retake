"""FastAPI application entry point. Routers are registered here; logic lives in services."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from retake import __version__
from retake.api.errors import register_error_handlers
from retake.api.routers import projects, takes
from retake.config import get_settings
from retake.integrations.elevenlabs.client import build_client_from_settings
from retake.integrations.elevenlabs.tts import TtsClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Process-wide resources: built once before the first request, closed after the last.

    The httpx client is the connection pool for api.elevenlabs.io; `async with` closes it on
    shutdown. Everything before `yield` is startup, everything after is teardown (the Python
    equivalent of a paired onModuleInit/onModuleDestroy in one function).
    """
    settings = get_settings()
    async with build_client_from_settings(settings) as http:
        app.state.tts = TtsClient.from_settings(http, settings)
        yield


app = FastAPI(title="Retake", version=__version__, lifespan=lifespan)
register_error_handlers(app)
app.include_router(projects.router)
app.include_router(takes.router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.environment, "version": __version__}
