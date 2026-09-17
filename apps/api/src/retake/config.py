"""Application settings, loaded from environment variables (and `.env` in dev).

Everything except the ElevenLabs API key has a default so that tests and CI
run without an object store or a real key (see REQUIREMENTS R20).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The single .env lives at the repository root (../../../../ from this file). Commands run
# from apps/api (alembic, uvicorn, pytest) still find it; a .env in the current directory
# wins if present; missing files are ignored (containers get their values from compose).
_REPO_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT_ENV, ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["dev", "test", "prod"] = "dev"

    database_url: str = "postgresql+asyncpg://retake:retake@localhost:5432/retake"
    # Connections held open per process. Every concurrent job holds one session, so this
    # must be >= GENERATION_CONCURRENCY, otherwise jobs queue for a connection instead of
    # waiting on ElevenLabs. Validated below.
    database_pool_size: PositiveInt = Field(default=5)
    redis_url: str = "redis://localhost:6379/0"

    object_store_endpoint: str = "http://localhost:9000"
    object_store_bucket: str = "retake"
    object_store_access_key: str = "minio"
    object_store_secret_key: SecretStr = SecretStr("minio12345")

    # SecretStr: repr/str print '**********', so the key cannot leak via a log line
    # or an error message. Hard rule 1 in CLAUDE.md.
    elevenlabs_api_key: SecretStr
    elevenlabs_default_voice_id: str = "replace-me"
    elevenlabs_default_model_id: str = "eleven_multilingual_v2"
    # Credits are integers (hard rule 7).
    elevenlabs_monthly_budget: PositiveInt = Field(default=50_000)

    generation_concurrency: PositiveInt = Field(default=3)

    @model_validator(mode="after")
    def _pool_covers_concurrency(self) -> "Settings":
        if self.generation_concurrency > self.database_pool_size:
            msg = (
                f"GENERATION_CONCURRENCY={self.generation_concurrency} exceeds "
                f"DATABASE_POOL_SIZE={self.database_pool_size}; "
                "each concurrent job needs its own connection"
            )
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process. Cached so every caller sees the same object."""
    return Settings()
