"""Every ErrorCode must map to an HTTP status, or the handler would raise KeyError (a 500)."""

from retake.api.errors import STATUS_BY_CODE
from retake.services.errors import ErrorCode, ServiceError


def test_every_error_code_has_a_status() -> None:
    assert set(STATUS_BY_CODE) == set(ErrorCode)


def test_service_error_subclass_without_code_is_rejected_at_definition() -> None:
    try:

        class Forgotten(ServiceError):
            pass
    except TypeError as exc:
        assert "must define a `code`" in str(exc)
    else:
        raise AssertionError("subclass without `code` was accepted")
