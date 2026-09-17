"""Shared test fixtures.

The API key is the only setting without a default. Tests must never need a real
one, so we inject a placeholder before the app module is imported.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ELEVENLABS_API_KEY", "test-not-a-real-key")
os.environ.setdefault("ENVIRONMENT", "test")

from retake.api.main import app  # must come after the env setup above


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client that talks to the app in-process, without a socket."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
