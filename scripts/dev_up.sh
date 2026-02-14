#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/artifacts/runtime"
mkdir -p "$RUNTIME_DIR"

BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
GATEWAY_PID_FILE="$RUNTIME_DIR/openclaw-gateway.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
GATEWAY_LOG="$RUNTIME_DIR/openclaw-gateway.log"

export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:$PATH"

is_pid_alive() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

start_backend() {
  if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1; then
    echo "[backend] already healthy"
    return
  fi

  if [[ -f "$BACKEND_PID_FILE" ]]; then
    local pid
    pid="$(cat "$BACKEND_PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && is_pid_alive "$pid"; then
      echo "[backend] process already running (pid=$pid), waiting for health..."
      sleep 2
      return
    fi
  fi

  nohup "$ROOT_DIR/scripts/run_backend.sh" >"$BACKEND_LOG" 2>&1 &
  echo "$!" >"$BACKEND_PID_FILE"
  echo "[backend] started pid=$(cat "$BACKEND_PID_FILE")"
}

start_gateway() {
  if command -v openclaw >/dev/null 2>&1 && openclaw --profile word-assistant health --json >/dev/null 2>&1; then
    echo "[openclaw] gateway already healthy"
    return
  fi

  if [[ -f "$GATEWAY_PID_FILE" ]]; then
    local pid
    pid="$(cat "$GATEWAY_PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && is_pid_alive "$pid"; then
      echo "[openclaw] gateway process already running (pid=$pid), waiting for health..."
      sleep 2
      return
    fi
  fi

  nohup "$ROOT_DIR/scripts/run_openclaw_gateway.sh" >"$GATEWAY_LOG" 2>&1 &
  echo "$!" >"$GATEWAY_PID_FILE"
  echo "[openclaw] gateway started pid=$(cat "$GATEWAY_PID_FILE")"
}

start_backend
start_gateway

sleep 3
"$ROOT_DIR/scripts/dev_status.sh"
