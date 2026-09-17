"""Map service errors and validation errors to the uniform ErrorResponse body."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from retake.api.schemas.errors import ErrorResponse
from retake.services.errors import ErrorCode, ServiceError

# HTTP is an API-layer concern; services only know their ErrorCode.
STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.PROJECT_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PROJECT_ALREADY_IMPORTED: status.HTTP_409_CONFLICT,
    ErrorCode.NOTHING_TO_IMPORT: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # 402 for the local budget cap on purpose: the client distinguishes it from ElevenLabs'
    # own 402 by `code` (budget_exceeded vs paid_plan_required).
    ErrorCode.BUDGET_EXCEEDED: status.HTTP_402_PAYMENT_REQUIRED,
    ErrorCode.LEDGER_ENTRY_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.LEDGER_LOCKED: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _error_response(status_code: int, code: ErrorCode, detail: str) -> JSONResponse:
    body = ErrorResponse(detail=detail, code=code)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def service_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ServiceError):  # registered for ServiceError only
        raise TypeError(f"service_error_handler got {type(exc).__name__}")
    return _error_response(STATUS_BY_CODE[exc.code], exc.code, exc.detail)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError(f"validation_error_handler got {type(exc).__name__}")
    # "body.title: String should have at least 1 character; body.text: ..."
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    detail = "; ".join(parts) or "Invalid request"
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, detail
    )


def register_error_handlers(app: FastAPI) -> None:
    # TODO(week 9, hardening): handler for unexpected exceptions that returns the same
    # {detail, code} body for 500 and logs via structlog; until then FastAPI's default applies.
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
