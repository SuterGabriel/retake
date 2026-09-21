import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from retake.db.models import TakeStatus


class GenerateRequest(BaseModel):
    """Optional body of POST /segments/{id}/generate. `attempt` is the ledger's idempotency
    dimension: the same attempt never calls the API twice; a new attempt is a new row."""

    attempt: int = Field(default=1, ge=1)


class TakeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    segment_id: uuid.UUID
    segment_version: int
    attempt: int
    status: TakeStatus
    credits: int
    duration_ms: int | None
    is_active: bool
    request_id: str | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def audio_url(self) -> str | None:
        """Relative URL of the audio, or null while there is none (generating, failed)."""
        if self.status != TakeStatus.DONE:
            return None
        return f"/takes/{self.id}/audio"
