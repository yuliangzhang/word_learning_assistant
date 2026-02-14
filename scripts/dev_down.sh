#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/artifacts/runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
GATEWAY_PID_FILE="$RUNTIME_DIR/openclaw-gateway.pid"

stop_by_pid_file() {
  local label="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "[$label] pid file missing, nothing to stop"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "${pid:-}" ]]; then
    echo "[$label] pid file empty"
    rm -f "$pid_file"
    return
  fi

  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    echo "[$label] stopped pid=$pid"
  else
    echo "[$label] stale pid=$pid"
  fi

  rm -f "$pid_file"
}

stop_by_pid_file "backend" "$BACKEND_PID_FILE"
stop_by_pid_file "openclaw" "$GATEWAY_PID_FILE"
