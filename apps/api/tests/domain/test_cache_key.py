"""`domain.cache_key.content_hash`: the identity of a generation request.

Same inputs -> same hash (cache hit, no API call); any change in text, voice, model, settings
or neighbouring context -> different hash. Pure function, hex SHA-256.
"""

import re
from typing import Any

from retake.domain.cache_key import content_hash

BASE: dict[str, Any] = dict(
    text="Chapter one.",
    voice_id="voice-1",
    model_id="eleven_multilingual_v2",
    voice_settings={"stability": 0.7, "similarity_boost": 0.75},
    previous_text="Before.",
    next_text="After.",
)


def test_is_a_hex_sha256() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", content_hash(**BASE))


def test_same_inputs_same_hash() -> None:
    assert content_hash(**BASE) == content_hash(**BASE)


def test_voice_settings_key_order_does_not_matter() -> None:
    reordered = {**BASE, "voice_settings": {"similarity_boost": 0.75, "stability": 0.7}}

    assert content_hash(**BASE) == content_hash(**reordered)


def test_changed_next_text_is_a_different_hash() -> None:
    assert content_hash(**BASE) != content_hash(**{**BASE, "next_text": "Other."})


def test_missing_context_differs_from_empty_context() -> None:
    assert content_hash(**{**BASE, "next_text": None}) != content_hash(**{**BASE, "next_text": ""})


def test_every_field_is_part_of_the_identity() -> None:
    variants: list[dict[str, Any]] = [
        {"text": "Chapter two."},
        {"voice_id": "voice-2"},
        {"model_id": "eleven_v3"},
        {"voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
        {"previous_text": None},
    ]
    hashes = {content_hash(**{**BASE, **change}) for change in variants}

    assert len(hashes) == len(variants)
    assert content_hash(**BASE) not in hashes
