"""One `httpx.AsyncClient` per process for api.elevenlabs.io.

The client *is* the connection pool: it keeps TLS connections open between requests, so it is
built once (FastAPI lifespan, arq on_startup) and injected into the adapters, never created per
call. Timeouts are explicit per phase (python.md): `read` is the long one, because the audio
only arrives after synthesis.
"""

import httpx

from retake.config import Settings

CONNECT_TIMEOUT_S = 5.0
WRITE_TIMEOUT_S = 10.0
POOL_TIMEOUT_S = 5.0


def build_client(
    api_key: str, *, base_url: str, read_timeout_s: float = 60.0, max_connections: int = 10
) -> httpx.AsyncClient:
    """The API key lives only in the default headers; httpx never prints headers in reprs or
    exception messages, so it cannot leak through this object (covered by tests)."""
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"xi-api-key": api_key, "accept": "application/json"},
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_S,
            read=read_timeout_s,
            write=WRITE_TIMEOUT_S,
            pool=POOL_TIMEOUT_S,
        ),
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=5),
    )


def build_client_from_settings(settings: Settings) -> httpx.AsyncClient:
    return build_client(
        settings.elevenlabs_api_key.get_secret_value(),
        base_url=settings.elevenlabs_base_url,
        read_timeout_s=settings.elevenlabs_read_timeout_s,
        max_connections=settings.generation_concurrency + 2,
    )
