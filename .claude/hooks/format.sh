#!/usr/bin/env bash
# PostToolUse hook: format the file Claude just edited. Reads tool input JSON on stdin.
set -euo pipefail
file=$(jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0
root=$(git rev-parse --show-toplevel)
case "$file" in
  */apps/api/*.py)
    (cd "$root/apps/api" && uv run ruff check --fix -q "$file" && uv run ruff format -q "$file") || true ;;
  */apps/web/*.ts|*/apps/web/*.tsx|*/apps/web/*.css)
    (cd "$root/apps/web" && npx prettier --write --log-level silent "$file") || true ;;
esac
