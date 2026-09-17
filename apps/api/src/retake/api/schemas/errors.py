from pydantic import BaseModel

from retake.services.errors import ErrorCode


class ErrorResponse(BaseModel):
    """Body of every 4xx response. `code` is stable and machine-readable, `detail` is for humans."""

    detail: str
    code: ErrorCode
