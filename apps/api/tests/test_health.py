from httpx import AsyncClient

from retake.config import Settings


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


async def test_api_key_never_appears_in_health_response(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert "test-not-a-real-key" not in response.text


def test_settings_do_not_print_the_api_key() -> None:
    settings = Settings(elevenlabs_api_key="super-secret")

    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings)
    assert settings.elevenlabs_api_key.get_secret_value() == "super-secret"
