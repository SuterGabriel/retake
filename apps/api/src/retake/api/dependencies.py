"""FastAPI dependencies. One AsyncSession per request; closed when the handler returns.

Routers receive services, never the session: the service is the unit of work and decides
where the transaction ends. Verified by the rollback test in tests/api/test_projects.py.

Process-wide objects (the ElevenLabs client) are created in the lifespan (api/main.py) and
read from `app.state` here; tests replace `get_tts_client` and `get_audio_store` through
`app.dependency_overrides` so no request ever needs a real key or a fixed directory.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from retake.config import get_settings
from retake.db.session import SessionFactory
from retake.integrations.audio_store import AudioStore, LocalAudioStore
from retake.integrations.elevenlabs.tts import TtsClient
from retake.services.generation import GenerationService
from retake.services.ledger import LedgerService
from retake.services.projects import ProjectService
from retake.services.takes import TakeService


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:  # __aexit__ rolls back anything uncommitted
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(session)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def get_tts_client(request: Request) -> TtsClient:
    tts = getattr(request.app.state, "tts", None)
    if tts is None:  # lifespan did not run (or was skipped): a wiring bug, not a client error
        raise RuntimeError("TtsClient is not initialised; the app lifespan must run")
    if not isinstance(tts, TtsClient):
        raise TypeError(f"app.state.tts is {type(tts).__name__}, expected TtsClient")
    return tts


def get_audio_store() -> AudioStore:
    return LocalAudioStore(get_settings().audio_store_path)


TtsClientDep = Annotated[TtsClient, Depends(get_tts_client)]
AudioStoreDep = Annotated[AudioStore, Depends(get_audio_store)]


def get_generation_service(
    session: SessionDep, tts: TtsClientDep, store: AudioStoreDep
) -> GenerationService:
    # Settings are read per request so the budget can change without a restart (and so tests
    # can patch it).
    ledger = LedgerService(session, get_settings())
    return GenerationService(session, ledger=ledger, tts=tts, store=store)


def get_take_service(session: SessionDep, store: AudioStoreDep) -> TakeService:
    return TakeService(session, store=store)


GenerationServiceDep = Annotated[GenerationService, Depends(get_generation_service)]
TakeServiceDep = Annotated[TakeService, Depends(get_take_service)]
