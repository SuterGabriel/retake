import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_CHAPTER_CHARACTERS = 50_000  # R1

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Omitted or null means "use the default from settings"; an empty string is rejected.
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class ProjectCreate(BaseModel):
    title: Title
    voice_id: Identifier | None = None
    model_id: Identifier | None = None
    voice_settings: dict[str, Any] = Field(default_factory=dict)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # build from the SQLAlchemy object

    id: uuid.UUID
    title: str
    voice_id: str
    model_id: str
    voice_settings: dict[str, Any]
    created_at: datetime


class ImportRequest(BaseModel):
    """Chapter text as sent by the browser after reading the TXT/Markdown file (R1)."""

    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_CHAPTER_CHARACTERS)]


class SegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    paragraph_index: int
    text: str
    version: int


class ImportResult(BaseModel):
    project_id: uuid.UUID
    segment_count: int
    segments: list[SegmentRead]
