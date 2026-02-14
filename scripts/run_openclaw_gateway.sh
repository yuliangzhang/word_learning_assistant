#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:$PATH"

PROFILE="${OPENCLAW_PROFILE:-word-assistant}"
PORT="${OPENCLAW_GATEWAY_PORT:-18789}"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "openclaw command not found in PATH." >&2
  exit 1
fi

exec openclaw --profile "$PROFILE" gateway run --port "$PORT"
