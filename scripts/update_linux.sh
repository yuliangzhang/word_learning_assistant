#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/word_learning_assistant}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-word-learning-assistant}"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
APP_PORT="${APP_PORT:-8000}"

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    if ! command -v sudo >/dev/null 2>&1; then
      echo "sudo is required for this operation." >&2
      exit 1
    fi
    sudo "$@"
  fi
}

run_as_user() {
  local cmd="$1"
  if [[ "${EUID}" -eq 0 ]]; then
    sudo -u "$APP_USER" bash -lc "$cmd"
  else
    bash -lc "$cmd"
  fi
}

if [[ ! -d "$APP_DIR/.git" ]]; then
  echo "Repo not found: $APP_DIR"
  exit 1
fi

echo "==> Pulling latest code..."
run_as_user "cd '$APP_DIR' && git fetch origin && git checkout '$BRANCH' && git pull --ff-only origin '$BRANCH'"

echo "==> Installing/refreshing dependencies..."
run_as_user "cd '$APP_DIR' && .venv/bin/pip install --upgrade pip setuptools wheel && .venv/bin/pip install -r requirements.txt"

echo "==> Restarting service..."
run_root systemctl daemon-reload
run_root systemctl restart "$SERVICE_NAME"
run_root systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,20p'
echo "==> Health check:"
curl -fsS "http://127.0.0.1:$APP_PORT/health" || true

echo "Update done."
