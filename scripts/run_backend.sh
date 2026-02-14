#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${WORD_ASSISTANCE_PYTHON:-}" ]]; then
  PYTHON_BIN="$WORD_ASSISTANCE_PYTHON"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 not found. Set WORD_ASSISTANCE_PYTHON or create .venv first." >&2
  exit 1
fi

HOST="${WORD_ASSISTANCE_HOST:-127.0.0.1}"
PORT="${WORD_ASSISTANCE_PORT:-8000}"

exec "$PYTHON_BIN" -m uvicorn word_assistance.app:app --host "$HOST" --port "$PORT"
