#!/bin/bash
# Link this repo as a skill into every supported agent framework.
# Safe to re-run. Works from any checkout path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

BASES=(
  "$HOME/.workbuddy/skills"
  "$HOME/.claude/skills"
  "$HOME/.agents/skills"
  "$HOME/.codex/skills"
  "$HOME/.dsh/skills"
  "$HOME/.pi/agent/skills"
  "$HOME/.hermes/skills"
  "$HOME/.openclaw/workspace/skills"
)

echo "==> Linking social2md -> ${#BASES[@]} agent framework paths"
for base in "${BASES[@]}"; do
  mkdir -p "$base"
  ln -sfn "$ROOT" "$base/social2md"
  echo "    linked: $base/social2md"
done

echo "==> Done. Restart your agent (or open a new session) to pick up the skill."
