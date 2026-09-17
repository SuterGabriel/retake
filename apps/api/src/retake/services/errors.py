"""Errors a use case can raise. The API layer maps them to HTTP status codes.

`ErrorCode` is the machine-readable part of every error response; being a StrEnum it appears
in the OpenAPI schema as an enum, so the generated TypeScript client gets a union type.
"""

from enum import StrEnum
from typing import ClassVar


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    PROJECT_NOT_FOUND = "project_not_found"
    PROJECT_ALREADY_IMPORTED = "project_already_imported"
    NOTHING_TO_IMPORT = "nothing_to_import"
    BUDGET_EXCEEDED = "budget_exceeded"
    LEDGER_ENTRY_NOT_FOUND = "ledger_entry_not_found"
    LEDGER_LOCKED = "ledger_locked"


class ServiceError(Exception):
    """Base for errors that are part of a use case's contract (not bugs).

    Subclasses must set `code`; raising the base class directly is a programming error.
    """

    code: ClassVar[ErrorCode]

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "code" not in cls.__dict__:
            raise TypeError(f"{cls.__name__} must define a `code`")


class ProjectNotFound(ServiceError):
    code = ErrorCode.PROJECT_NOT_FOUND


class ProjectAlreadyImported(ServiceError):
    code = ErrorCode.PROJECT_ALREADY_IMPORTED


class NothingToImport(ServiceError):
    code = ErrorCode.NOTHING_TO_IMPORT


class BudgetExceeded(ServiceError):
    code = ErrorCode.BUDGET_EXCEEDED


class LedgerEntryNotFound(ServiceError):
    code = ErrorCode.LEDGER_ENTRY_NOT_FOUND


class LedgerLocked(ServiceError):
    """The budget row lock could not be taken in time; the caller may retry later."""

    code = ErrorCode.LEDGER_LOCKED
