"""Generate a take for a segment; serve a take's audio. Validate and delegate (rule 4)."""

import uuid
from typing import Any

from fastapi import APIRouter, Response, status

from retake.api.dependencies import GenerationServiceDep, TakeServiceDep
from retake.api.schemas.errors import ErrorResponse
from retake.api.schemas.takes import GenerateRequest, TakeRead

router = APIRouter(tags=["takes"])

_ERR: dict[int | str, dict[str, Any]] = {
    status.HTTP_402_PAYMENT_REQUIRED: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
}


@router.post(
    "/segments/{segment_id}/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=TakeRead,
    responses=_ERR,
)
async def generate_take(
    segment_id: uuid.UUID, service: GenerationServiceDep, data: GenerateRequest | None = None
) -> TakeRead:
    """201 also for a `failed` take: the upstream refusal is a recorded outcome (take + ledger),
    the caller inspects `status`. Only use-case errors become 4xx."""
    attempt = data.attempt if data is not None else 1
    take = await service.generate_take(segment_id, attempt=attempt)
    return TakeRead.model_validate(take)


@router.get(
    "/takes/{take_id}/audio",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {"audio/mpeg": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def take_audio(take_id: uuid.UUID, service: TakeServiceDep) -> Response:
    """Whole file in one response. A sentence of MP3 is a few hundred KB; chunked streaming
    (and range requests for seeking) become relevant with chapter exports in week 8."""
    audio = await service.audio(take_id)
    return Response(content=audio, media_type="audio/mpeg")
