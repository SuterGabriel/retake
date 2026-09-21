"""The identity of a generation request: same inputs, same audio, no second API call.

`content_hash` covers everything that changes the audio ElevenLabs returns: the text, the
voice, the model, the voice settings and the neighbouring text sent as context (the model
conditions prosody on it). Two takes with equal hashes are interchangeable, so the second
one can reuse the first one's audio for free (services/generation.py, the cache path).

Pure function (hard rule 3): no I/O, no database, deterministic across processes.
"""

import hashlib
import json
from collections.abc import Mapping


def content_hash(
    *,
    text: str,
    voice_id: str,
    model_id: str,
    voice_settings: Mapping[str, object],
    previous_text: str | None,
    next_text: str | None,
) -> str:
    """Hex SHA-256 over a canonical JSON encoding of the inputs.

    Canonical means: keys sorted at every nesting level, no whitespace, non-ASCII kept as is.
    `None` is encoded as JSON `null` and an empty string as `""`, so "no context" and "empty
    context" hash differently: the adapter omits the field for `None` but sends `""`, and the
    API may treat those differently.
    """
    payload = {
        "text": text,
        "voice_id": voice_id,
        "model_id": model_id,
        "voice_settings": dict(voice_settings),
        "previous_text": previous_text,
        "next_text": next_text,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
