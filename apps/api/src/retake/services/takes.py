"""TakeService: the read side of takes (the audio bytes for the player)."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from retake.db.models import Take
from retake.integrations.audio_store import AudioNotFound, AudioStore
from retake.services.errors import TakeHasNoAudio, TakeNotFound


class TakeService:
    def __init__(self, session: AsyncSession, *, store: AudioStore) -> None:
        self._session = session
        self._store = store

    async def audio(self, take_id: uuid.UUID) -> bytes:
        take = await self._session.get(Take, take_id)
        if take is None:
            raise TakeNotFound(f"Take {take_id} not found")
        if take.audio_key is None:
            raise TakeHasNoAudio(f"Take {take_id} is {take.status.value} and has no audio")
        try:
            return await self._store.get(take.audio_key)
        except AudioNotFound as exc:
            # The row says there is audio but the store has none: data loss on our side, but
            # from the client's point of view the resource is simply gone.
            raise TakeHasNoAudio(f"Audio for take {take_id} is missing from the store") from exc
