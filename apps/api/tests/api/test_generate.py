"""HTTP contract of POST /segments/{id}/generate and GET /takes/{id}/audio.

The app's TtsClient and audio store are swapped via dependency overrides; ElevenLabs is
mocked with respx; the database is real (rolled-back session from conftest).
"""

import base64
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from retake.api.dependencies import get_audio_store, get_tts_client
from retake.api.main import app
from retake.config import get_settings
from retake.db.models import LedgerKind
from retake.integrations.audio_store import LocalAudioStore
from retake.integrations.elevenlabs.client import build_client
from retake.integrations.elevenlabs.tts import TtsClient
from retake.services.ledger import LedgerService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "elevenlabs"
BASE_URL = "https://api.elevenlabs.io"
TTS_PATH = r"/v1/text-to-speech/.+/with-timestamps"
CHAPTER = "First one. Second one."


def tts_ok() -> httpx.Response:
    body = json.loads((FIXTURES / "tts-with-timestamps.v2.json").read_text(encoding="utf-8"))
    return httpx.Response(200, json=body, headers={"character-cost": "79", "request-id": "req-1"})


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[None]:
    """Give the app a test TtsClient and a temp audio store for the duration of a test."""
    async with build_client("sk-test", base_url=BASE_URL) as http:
        tts = TtsClient(
            http, concurrency=2, sleep=no_sleep, max_attempts=2, max_concurrency_waits=1
        )
        store = LocalAudioStore(tmp_path / "audio")
        app.dependency_overrides[get_tts_client] = lambda: tts
        app.dependency_overrides[get_audio_store] = lambda: store
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_tts_client, None)
            app.dependency_overrides.pop(get_audio_store, None)


async def import_chapter(client: AsyncClient) -> tuple[str, list[dict[str, object]]]:
    """Returns (project_id, segments)."""
    project = (await client.post("/projects", json={"title": "Gen"})).json()
    result = await client.post(f"/projects/{project['id']}/import", json={"text": CHAPTER})
    assert result.status_code == 200, result.text
    return str(project["id"]), list(result.json()["segments"])


# ---------------------------------------------------------------- POST /segments/{id}/generate


@pytest.mark.usefixtures("wired")
async def test_generate_returns_201_with_the_take(
    client: AsyncClient, api: respx.MockRouter
) -> None:
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())

    response = await client.post(f"/segments/{segments[0]['id']}/generate")

    assert response.status_code == 201, response.text
    body = response.json()
    uuid.UUID(body["id"])
    assert body["segment_id"] == segments[0]["id"]
    assert body["status"] == "done"
    assert body["attempt"] == 1
    assert body["credits"] == 79
    assert body["duration_ms"] == 5619
    assert body["is_active"] is True
    assert body["audio_url"] == f"/takes/{body['id']}/audio"


@pytest.mark.usefixtures("wired")
async def test_generate_accepts_an_explicit_attempt(
    client: AsyncClient, api: respx.MockRouter
) -> None:
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    await client.post(f"/segments/{segments[0]['id']}/generate")

    response = await client.post(f"/segments/{segments[0]['id']}/generate", json={"attempt": 2})

    assert response.status_code == 201
    assert response.json()["attempt"] == 2
    assert response.json()["credits"] == 0  # cache hit: same text, voice, model, context


@pytest.mark.usefixtures("wired")
async def test_generate_unknown_segment_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/segments/{uuid.uuid4()}/generate")

    assert response.status_code == 404
    assert response.json()["code"] == "segment_not_found"


@pytest.mark.usefixtures("wired")
async def test_generate_over_budget_returns_402(
    client: AsyncClient, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, segments = await import_chapter(client)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    monkeypatch.setattr(get_settings(), "elevenlabs_monthly_budget", 3)

    response = await client.post(f"/segments/{segments[0]['id']}/generate")

    assert response.status_code == 402
    assert response.json()["code"] == "budget_exceeded"
    assert route.call_count == 0


@pytest.mark.usefixtures("wired")
async def test_generate_failed_upstream_returns_201_with_failed_take(
    client: AsyncClient, api: respx.MockRouter
) -> None:
    """An upstream refusal is a recorded outcome (take + ledger), not an HTTP error: the
    caller inspects `status`."""
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(
            402,
            json={
                "detail": {
                    "type": "payment_required",
                    "code": "paid_plan_required",
                    "message": "m",
                    "status": "payment_required",
                }
            },
        )
    )

    response = await client.post(f"/segments/{segments[0]['id']}/generate")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["audio_url"] is None
    assert body["credits"] == 0


@pytest.mark.usefixtures("wired")
async def test_generate_same_attempt_after_crash_returns_409(
    client: AsyncClient, api: respx.MockRouter, session: AsyncSession
) -> None:
    project_id, segments = await import_chapter(client)
    route = api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    # a pending reservation for attempt 1, as left behind by a run that died after the API call
    await LedgerService(session, get_settings()).reserve(
        project_id=uuid.UUID(project_id),
        kind=LedgerKind.TTS,
        segment_id=uuid.UUID(str(segments[0]["id"])),
        segment_version=1,
        attempt=1,
        estimated_credits=10,
    )

    response = await client.post(f"/segments/{segments[0]['id']}/generate")

    assert response.status_code == 409
    assert response.json()["code"] == "attempt_already_in_flight"
    assert "attempt 2" in response.json()["detail"]
    assert route.call_count == 0


# ---------------------------------------------------------------- GET /takes/{id}/audio


@pytest.mark.usefixtures("wired")
async def test_audio_streams_the_stored_bytes(client: AsyncClient, api: respx.MockRouter) -> None:
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    take = (await client.post(f"/segments/{segments[0]['id']}/generate")).json()

    response = await client.get(take["audio_url"])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == base64.b64decode("QUFBQQ==")


@pytest.mark.usefixtures("wired")
async def test_audio_of_unknown_take_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/takes/{uuid.uuid4()}/audio")

    assert response.status_code == 404
    assert response.json()["code"] == "take_not_found"


@pytest.mark.usefixtures("wired")
async def test_audio_of_failed_take_returns_404(client: AsyncClient, api: respx.MockRouter) -> None:
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(
        return_value=httpx.Response(401, json={"detail": {"code": "invalid_api_key"}})
    )
    take = (await client.post(f"/segments/{segments[0]['id']}/generate")).json()

    response = await client.get(f"/takes/{take['id']}/audio")

    assert response.status_code == 404
    assert response.json()["code"] == "take_has_no_audio"


@pytest.mark.usefixtures("wired")
async def test_audio_missing_from_the_store_returns_404(
    client: AsyncClient, api: respx.MockRouter, tmp_path: Path
) -> None:
    """The row says there is audio, the store has none (deleted, wrong volume): from the
    client's side the resource is gone, so 404 with the same code as a take without audio."""
    _, segments = await import_chapter(client)
    api.post(path__regex=TTS_PATH).mock(return_value=tts_ok())
    take = (await client.post(f"/segments/{segments[0]['id']}/generate")).json()
    stored = tmp_path / "audio" / "takes" / f"{take['id']}.mp3"
    assert stored.is_file()
    stored.unlink()

    response = await client.get(take["audio_url"])

    assert response.status_code == 404
    assert response.json()["code"] == "take_has_no_audio"
