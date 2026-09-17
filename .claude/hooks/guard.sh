#!/usr/bin/env bash
# PreToolUse hook for Bash: block destructive or secret-leaking commands. Exit code 2 blocks the tool call.
# Defence in depth only: gitleaks (pre-commit) and GitHub Push Protection are the real guard rails.
# Requires bash + jq (on Windows: Git Bash).
# Deliberately NOT blocked: reading .env.example, `uv venv`, `alembic downgrade -1` (normal migration testing).
set -euo pipefail
cmd=$(jq -r '.tool_input.command // empty')
deny='(git push[^|]*(--force|-f\b)|git reset --hard|git clean -fd|rm -rf (/|\.|~)|(cat|type|head|tail|less|more|bat|Get-Content|gc|source|\.) [^|;&]*\.env(\.(local|dev|prod|production|test))?($|[ ;&|])|printenv|(^|[ ;&|])env$|echo \$\{?ELEVENLABS|alembic downgrade base|DROP (TABLE|DATABASE))'
if echo "$cmd" | grep -Eiq "$deny"; then
  echo "Blocked by .claude/hooks/guard.sh: $cmd" >&2
  exit 2
fi
exit 0
