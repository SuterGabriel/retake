"""HTTP contract of POST /projects and POST /projects/{id}/import.

Routers validate and delegate; these tests check status codes, response shapes and the
uniform error body {detail, code}. They run through the in-process client on the
rolled-back test session (conftest.py).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from retake.api.dependencies import SessionDep
from retake.api.main import app
from retake.db.models import Project
from retake.db.session import SessionFactory, engine

CHAPTER = "First one. First two.\n\nSecond one."


async def _create_project(client: AsyncClient, **overrides: object) -> dict[str, object]:
    response = await client.post("/projects", json={"title": "Chapter 1", **overrides})
    assert response.status_code == 201, response.text
    return dict(response.json())


# ---------------------------------------------------------------- POST /projects


async def test_create_project_returns_201_and_the_project(client: AsyncClient) -> None:
    response = await client.post("/projects", json={"title": "Chapter 1"})

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])  # a valid uuid
    assert body["title"] == "Chapter 1"
    assert body["voice_id"]  # default from settings
    assert body["model_id"]
    assert body["voice_settings"] == {}
    assert body["created_at"].endswith(("Z", "+00:00"))


async def test_create_project_accepts_voice_model_and_settings(client: AsyncClient) -> None:
    body = await _create_project(
        client, voice_id="voice-x", model_id="model-y", voice_settings={"stability": 0.4}
    )

    assert (body["voice_id"], body["model_id"]) == ("voice-x", "model-y")
    assert body["voice_settings"] == {"stability": 0.4}


@pytest.mark.parametrize(
    "payload",
    [
        {},  # title missing
        {"title": ""},  # title empty
        {"title": "   "},  # title blank
        {"title": "x" * 201},  # title too long
        {"title": "ok", "voice_settings": "not-an-object"},
        {"title": "ok", "voice_id": ""},  # empty is not "use the default"
        {"title": "ok", "model_id": "   "},
    ],
)
async def test_create_project_rejects_invalid_payload_with_422(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post("/projects", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], str) and body["detail"]


# ---------------------------------------------------------------- POST /projects/{id}/import


async def test_import_returns_segments_in_position_order(client: AsyncClient) -> None:
    project = await _create_project(client)

    response = await client.post(f"/projects/{project['id']}/import", json={"text": CHAPTER})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["segment_count"] == 3
    assert [(s["position"], s["paragraph_index"], s["text"]) for s in body["segments"]] == [
        (0, 0, "First one."),
        (1, 0, "First two."),
        (2, 1, "Second one."),
    ]
    assert all(uuid.UUID(s["id"]) for s in body["segments"])
    assert all(s["version"] == 1 for s in body["segments"])


async def test_import_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.post(f"/projects/{uuid.uuid4()}/import", json={"text": CHAPTER})

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == "project_not_found"
    assert "not found" in body["detail"].lower()


async def test_import_malformed_project_id_returns_422(client: AsyncClient) -> None:
    response = await client.post("/projects/not-a-uuid/import", json={"text": CHAPTER})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_second_import_returns_409(client: AsyncClient) -> None:
    project = await _create_project(client)
    await client.post(f"/projects/{project['id']}/import", json={"text": CHAPTER})

    response = await client.post(f"/projects/{project['id']}/import", json={"text": "Again."})

    assert response.status_code == 409
    assert response.json()["code"] == "project_already_imported"


@pytest.mark.parametrize(
    "text",
    ["", "x" * 50_001],
    ids=["empty", "over-50k-characters"],
)
async def test_import_rejects_invalid_text_with_422(client: AsyncClient, text: str) -> None:
    project = await _create_project(client)

    response = await client.post(f"/projects/{project['id']}/import", json={"text": text})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_import_with_only_comments_returns_422_nothing_to_import(
    client: AsyncClient,
) -> None:
    project = await _create_project(client)

    response = await client.post(
        f"/projects/{project['id']}/import", json={"text": "// header only\n\n"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "nothing_to_import"


async def test_import_accepts_exactly_50k_characters(client: AsyncClient) -> None:
    project = await _create_project(client)
    text = ("Word. " * 8_334)[:50_000]

    response = await client.post(f"/projects/{project['id']}/import", json={"text": text})

    assert response.status_code == 200, response.text


# ---------------------------------------------------------------- session rollback


async def test_handler_that_raises_after_an_insert_leaves_nothing_behind() -> None:
    """Uses the real `get_session` (no override) and a throw-away route.

    The `async with SessionFactory()` in get_session must roll back on an exception, so a
    half-done request never persists. Verified with a fresh session afterwards.
    """
    marker = f"rollback-probe-{uuid.uuid4()}"

    async def raise_after_insert(session: SessionDep) -> None:
        session.add(Project(title=marker, voice_id="v", model_id="m"))
        await session.flush()
        raise RuntimeError("boom after insert")

    app.add_api_route("/_test/raise-after-insert", raise_after_insert, methods=["POST"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            with pytest.raises(RuntimeError, match="boom after insert"):
                await c.post("/_test/raise-after-insert")
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test/raise-after-insert"
        ]

    try:
        async with SessionFactory() as fresh:
            leaked = await fresh.scalar(select(Project).where(Project.title == marker))
    finally:
        # asyncpg connections are bound to the event loop that created them and every test
        # gets its own loop: return the pooled connections so later tests start clean.
        await engine.dispose()
    assert leaked is None
