"""LocalAudioStore: round trip, missing keys, and keys that must never leave the root."""

import asyncio
from pathlib import Path

import pytest

from retake.integrations.audio_store import AudioNotFound, LocalAudioStore


async def test_put_then_get_round_trips_bytes(tmp_path: Path) -> None:
    store = LocalAudioStore(tmp_path / "audio")

    await store.put("takes/abc.mp3", b"\x00\x01\x02")

    assert await store.get("takes/abc.mp3") == b"\x00\x01\x02"
    assert (tmp_path / "audio" / "takes" / "abc.mp3").is_file()


async def test_get_of_unknown_key_raises_audio_not_found(tmp_path: Path) -> None:
    store = LocalAudioStore(tmp_path)

    with pytest.raises(AudioNotFound):
        await store.get("takes/missing.mp3")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../x.mp3",
        "takes/../../x.mp3",
        "..\\x.mp3",
        "/abs.mp3",
        "C:\\x.mp3",
        "takes\\x.mp3",
        ".",
    ],
)
async def test_keys_that_could_escape_the_root_are_refused(tmp_path: Path, key: str) -> None:
    store = LocalAudioStore(tmp_path / "audio")

    with pytest.raises(ValueError, match="invalid audio key"):
        await store.put(key, b"x")

    assert not await asyncio.to_thread(lambda: list(tmp_path.rglob("*.mp3")))


def test_repr_shows_the_root_only(tmp_path: Path) -> None:
    assert repr(LocalAudioStore(tmp_path)).startswith("LocalAudioStore(root=")
