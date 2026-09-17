"""Routers validate and delegate. No business logic here (CLAUDE.md rule 4)."""

import uuid
from typing import Any

from fastapi import APIRouter, status

from retake.api.dependencies import ProjectServiceDep
from retake.api.schemas.errors import ErrorResponse
from retake.api.schemas.projects import (
    ImportRequest,
    ImportResult,
    ProjectCreate,
    ProjectRead,
    SegmentRead,
)

router = APIRouter(prefix="/projects", tags=["projects"])

_VALIDATION: dict[int | str, dict[str, Any]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}
}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectRead,
    responses=_VALIDATION,
)
async def create_project(data: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    project = await service.create(
        title=data.title,
        voice_id=data.voice_id,
        model_id=data.model_id,
        voice_settings=data.voice_settings,
    )
    return ProjectRead.model_validate(project)


@router.post(
    "/{project_id}/import",
    response_model=ImportResult,
    responses={
        **_VALIDATION,
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def import_chapter(
    project_id: uuid.UUID, data: ImportRequest, service: ProjectServiceDep
) -> ImportResult:
    """200, not 201: import is an action on an existing project that returns a result,
    the created segments are addressed through the project, not as their own resource."""
    segments = await service.import_text(project_id, data.text)
    return ImportResult(
        project_id=project_id,
        segment_count=len(segments),
        segments=[SegmentRead.model_validate(s) for s in segments],
    )
