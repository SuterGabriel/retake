# ElevenLabs contract fixtures

Real responses captured with `infra/verify-elevenlabs.sh` on 2026-09-17 (Free plan, premade
voice, `eleven_multilingual_v2` / `eleven_v3`, `scribe_v2`). Used by the `respx` tests of the
adapter (week 2) and the detection pipeline (week 4). Never call the paid API in tests.

| File | What |
|---|---|
| `tts-with-timestamps.v2.json` | `POST /v1/text-to-speech/{voice}/with-timestamps`, v2, 79-character sentence. `audio_base64` replaced by a 4-byte placeholder; `alignment` and `normalized_alignment` are real. |
| `tts-with-timestamps.v3.json` | same request with `eleven_v3` |
| `scribe.plain.json` | `POST /v1/speech-to-text` on the v2 audio, no keyterms: the name comes back as "Zefora" |
| `scribe.keyterms.json` | same with `keyterms=Zyphora`: the name comes back as "Zyphora" |
| `error.402-paid-plan-required.json` | error body shape (`detail.code`), library voice on Free |
| `headers.json` | `character-cost` values seen per response |

Request ids and trace ids were removed. The input text was:
`Chapter one. Dr. Zyphora arrived at 7:30 p.m. and said, "Nobody knows my name."`
