#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/artifacts/runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
GATEWAY_PID_FILE="$RUNTIME_DIR/openclaw-gateway.pid"

export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:$PATH"

is_pid_alive() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

echo "=== Word Assistance Backend ==="
if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
  echo "health: ok (http://127.0.0.1:8000/health)"
else
  echo "health: down"
fi

if [[ -f "$BACKEND_PID_FILE" ]]; then
  backend_pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)"
  if [[ -n "${backend_pid:-}" ]] && is_pid_alive "$backend_pid"; then
    echo "pid: $backend_pid (alive)"
  else
    echo "pid: stale ($backend_pid)"
  fi
else
  echo "pid: not tracked"
fi

echo
echo "=== OpenClaw Gateway ==="
if command -v openclaw >/dev/null 2>&1 && openclaw --profile word-assistant health --json >/dev/null 2>&1; then
  echo "health: ok (http://127.0.0.1:18789/openclaw)"
else
  echo "health: down"
fi

if [[ -f "$GATEWAY_PID_FILE" ]]; then
  gateway_pid="$(cat "$GATEWAY_PID_FILE" 2>/dev/null || true)"
  if [[ -n "${gateway_pid:-}" ]] && is_pid_alive "$gateway_pid"; then
    echo "pid: $gateway_pid (alive)"
  else
    echo "pid: stale ($gateway_pid)"
  fi
else
  echo "pid: not tracked"
fi

echo
echo "logs:"
echo "- $RUNTIME_DIR/backend.log"
echo "- $RUNTIME_DIR/openclaw-gateway.log"
