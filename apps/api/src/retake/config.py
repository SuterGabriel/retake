"""Application settings, loaded from environment variables (and `.env` in dev).

Everything except the ElevenLabs API key has a default so that tests and CI
run without an object store or a real key (see REQUIREMENTS R20).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["dev", "test", "prod"] = "dev"

    database_url: str = "postgresql+asyncpg://retake:retake@localhost:5432/retake"
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


@lru_cache
def get_settings() -> Settings:
    """Build settings once per process. Cached so every caller sees the same object."""
    return Settings()
