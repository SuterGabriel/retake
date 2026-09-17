import pytest
from pydantic import ValidationError

from retake.config import Settings


def test_pool_size_must_cover_generation_concurrency() -> None:
    with pytest.raises(
        ValidationError, match="GENERATION_CONCURRENCY=6 exceeds DATABASE_POOL_SIZE=5"
    ):
        Settings(
            elevenlabs_api_key="k",  # type: ignore[arg-type]
            generation_concurrency=6,
            database_pool_size=5,
        )


def test_pool_size_equal_to_concurrency_is_allowed() -> None:
    settings = Settings(
        elevenlabs_api_key="k",  # type: ignore[arg-type]
        generation_concurrency=5,
        database_pool_size=5,
    )

    assert settings.database_pool_size == 5
