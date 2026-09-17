#!/usr/bin/env bash
# Live verification of the ElevenLabs API contract (docs/ELEVENLABS.md, "needs real API call").
# Reads ELEVENLABS_API_KEY and ELEVENLABS_DEFAULT_VOICE_ID from the repo-root .env, never prints
# the key, writes every response to $OUT (default /tmp/retake-elevenlabs).
#
#   bash infra/verify-elevenlabs.sh          # all: subscription, 8 TTS requests, Scribe
#   bash infra/verify-elevenlabs.sh tts      # TTS part only (costs ~390 characters)
#   bash infra/verify-elevenlabs.sh scribe   # Scribe only, reuses audio from a previous tts run
#
set -euo pipefail

MODE="${1:-all}"
case "$MODE" in all|tts|scribe) ;; *) echo "usage: $0 [all|tts|scribe]" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-/tmp/retake-elevenlabs}"
API="https://api.elevenlabs.io/v1"

# --- read values from .env without sourcing it (no shell expansion of other lines)
env_value() {
  grep -E "^$1=" "$ROOT/.env" | head -1 | cut -d= -f2- | sed -e 's/[[:space:]]*#.*$//' -e 's/^"//' -e 's/"$//'
}
KEY="$(env_value ELEVENLABS_API_KEY)"
VOICE="$(env_value ELEVENLABS_DEFAULT_VOICE_ID)"
MODEL="$(env_value ELEVENLABS_DEFAULT_MODEL_ID)"; MODEL="${MODEL:-eleven_multilingual_v2}"
if [ -z "$KEY" ] || [ "$KEY" = "replace-me" ]; then echo "ELEVENLABS_API_KEY missing in .env" >&2; exit 1; fi
if [ -z "$VOICE" ] || [ "$VOICE" = "replace-me" ]; then echo "ELEVENLABS_DEFAULT_VOICE_ID missing in .env" >&2; exit 1; fi
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
mkdir -p "$OUT"

# Windows-native curl does not translate /tmp/... inside "--form file=@..." (bare -o/-D args are
# translated by MSYS, form strings are not). cygpath gives the native path where available.
native_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

hdr() { grep -iE "^(character-cost|request-id|x-trace-id|retry-after|content-type|HTTP/)" "$1" | tr -d '\r' || true; }

subscription() {  # subscription <label>
  curl --fail-with-body -sS "$API/user/subscription" -H "xi-api-key: $KEY" -o "$OUT/subscription-$1.json"
  jq -r '"tier=\(.tier) used=\(.character_count) limit=\(.character_limit) status=\(.status)"' "$OUT/subscription-$1.json"
}

tts() {  # tts <name> <text> [output_format] [model]
  local name="$1" text="$2" fmt="${3:-mp3_44100_128}" model="${4:-$MODEL}"
  jq -n --arg t "$text" --arg m "$model" '{
    text: $t, model_id: $m,
    voice_settings: {stability: 0.7, similarity_boost: 0.75, style: 0.0, speed: 1.0, use_speaker_boost: true},
    apply_text_normalization: "auto"
  }' > "$OUT/tts-$name.request.json"
  local code
  code=$(curl -sS -w '%{http_code}' -X POST \
    "$API/text-to-speech/$VOICE/with-timestamps?output_format=$fmt" \
    -H "xi-api-key: $KEY" -H 'Content-Type: application/json' \
    -D "$OUT/tts-$name.headers.txt" -o "$OUT/tts-$name.json" \
    --data @"$OUT/tts-$name.request.json")
  printf '\n== TTS %-14s model=%s fmt=%s len(text)=%d http=%s\n' "$name" "$model" "$fmt" "${#text}" "$code"
  hdr "$OUT/tts-$name.headers.txt"
  if [ "$code" = "200" ]; then
    jq -r '"audio_base64_len=\(.audio_base64|length) chars_aligned=\(.alignment.characters|length) last_end_s=\(.alignment.character_end_times_seconds|last) normalized_chars=\(.normalized_alignment.characters|length)"' "$OUT/tts-$name.json"
    # Git Bash on Windows: strip CR/LF before decoding and ignore stray bytes (-i); a decode
    # failure is a warning, the JSON is already saved and the run continues.
    local ext="mp3"; case "$fmt" in pcm_*) ext="pcm" ;; wav_*) ext="wav" ;; opus_*) ext="opus" ;; esac
    if ! jq -r '.audio_base64' "$OUT/tts-$name.json" | tr -d '\r\n' | base64 -d -i > "$OUT/tts-$name.$ext" 2>/dev/null; then
      echo "warning: could not decode audio for $name (JSON kept at $OUT/tts-$name.json)"
      rm -f "$OUT/tts-$name.$ext"
    else
      echo "audio_file=$OUT/tts-$name.$ext bytes=$(wc -c < "$OUT/tts-$name.$ext")"
    fi
  else
    head -c 600 "$OUT/tts-$name.json"; echo
  fi
}

run_tts() {
  echo "== subscription before"; subscription before

  # 1. What counts as a character, minimum charge, rounding: compare character-cost with quota delta.
  tts one     "A"
  tts ten     "Ten chars!"
  tts hundred "$(printf 'x%.0s' $(seq 1 100))"
  # 2. Whitespace and punctuation: same letters, different whitespace.
  tts spaces  "Hello   world.   Again."
  tts nospace "Hello world. Again."
  # 3. Real sentence with abbreviation, number and name (normalisation + normalized_alignment).
  tts sentence 'Chapter one. Dr. Zyphora arrived at 7:30 p.m. and said, "Nobody knows my name."'
  # 4. Output format cost: same text as PCM.
  tts sentence-pcm 'Chapter one. Dr. Zyphora arrived at 7:30 p.m. and said, "Nobody knows my name."' pcm_22050
  # 5. Timestamps with v3 (model support matrix is undocumented).
  tts sentence-v3 'Chapter one. Dr. Zyphora arrived at 7:30 p.m. and said, "Nobody knows my name."' mp3_44100_128 eleven_v3

  echo; echo "== subscription after"; subscription after
  jq -r -n --slurpfile a "$OUT/subscription-before.json" --slurpfile b "$OUT/subscription-after.json" \
    '"quota delta (characters): \($b[0].character_count - $a[0].character_count)"'
  echo "sum of character-cost headers: $(grep -ihE '^character-cost:' "$OUT"/tts-*.headers.txt | awk '{s+=$2} END {print s+0}')"
}

run_scribe() {
  local audio="$OUT/tts-sentence.mp3"
  if [ ! -s "$audio" ]; then
    # older runs named the file .audio; otherwise take any decoded mp3
    for candidate in "$OUT/tts-sentence.audio" "$OUT"/tts-*.mp3; do
      [ -s "$candidate" ] && { audio="$candidate"; break; }
    done
  fi
  if [ ! -s "$audio" ]; then echo "no decoded audio in $OUT; run the tts part first" >&2; exit 1; fi
  local audio_native; audio_native="$(native_path "$audio")"
  echo "== Scribe input: $audio ($(wc -c < "$audio") bytes)"

  for variant in plain keyterms; do
    local args=(--form "file=@$audio_native;type=audio/mpeg" --form 'model_id=scribe_v2' --form 'language_code=eng'
                --form 'timestamps_granularity=word' --form 'diarize=false' --form 'tag_audio_events=false')
    [ "$variant" = keyterms ] && args+=(--form 'keyterms=Zyphora')
    local code
    code=$(curl -sS -w '%{http_code}' -X POST "$API/speech-to-text" -H "xi-api-key: $KEY" \
      -D "$OUT/scribe-$variant.headers.txt" -o "$OUT/scribe-$variant.json" "${args[@]}") || {
      echo "curl failed for scribe-$variant (exit $?)"; continue; }
    printf '\n== SCRIBE %-9s http=%s\n' "$variant" "$code"
    hdr "$OUT/scribe-$variant.headers.txt"
    if [ "$code" = "200" ]; then
      jq -r '"text=\(.text)"' "$OUT/scribe-$variant.json"
      jq -r '.words[] | select(.type=="word") | "\(.start)-\(.end)s \(.text) logprob=\(.logprob // "n/a")"' "$OUT/scribe-$variant.json" | head -20
      jq -r '"types: \([.words[].type] | group_by(.) | map("\(.[0])=\(length)") | join(", "))"' "$OUT/scribe-$variant.json"
      jq -r '"keys in words[0]: \(.words[0] | keys | join(", "))"' "$OUT/scribe-$variant.json"
    else
      head -c 600 "$OUT/scribe-$variant.json"; echo
    fi
  done
  echo; echo "== subscription after scribe"; subscription after-scribe
}

case "$MODE" in
  all)    run_tts; echo; run_scribe ;;
  tts)    run_tts ;;
  scribe) run_scribe ;;
esac
echo; echo "All responses are in $OUT. Do not commit them; the key is not in any file."
