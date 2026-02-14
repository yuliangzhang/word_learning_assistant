#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/yuliangzhang/word_learning_assistant.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/word_learning_assistant}"
APP_PORT="${APP_PORT:-8000}"
SERVICE_NAME="${SERVICE_NAME:-word-learning-assistant}"
APP_USER="${APP_USER:-${SUDO_USER:-$USER}}"
APP_GROUP="${APP_GROUP:-$(id -gn "$APP_USER")}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

run_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
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

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing command: $name"
    exit 1
  fi
}

install_base_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    run_root apt-get update -y
    run_root apt-get install -y git "$PYTHON_BIN" python3-venv python3-pip tesseract-ocr ffmpeg
  fi
}

echo "==> Installing system dependencies (if needed)..."
install_base_packages

require_cmd git
require_cmd "$PYTHON_BIN"

echo "==> Preparing source code in $APP_DIR ..."
if [[ -d "$APP_DIR/.git" ]]; then
  run_root git -C "$APP_DIR" fetch origin
  run_root git -C "$APP_DIR" checkout "$BRANCH"
  run_root git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  run_root mkdir -p "$(dirname "$APP_DIR")"
  run_root git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
run_root chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"

echo "==> Creating virtualenv and installing Python dependencies..."
run_as_user "cd '$APP_DIR' && '$PYTHON_BIN' -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt"

echo "==> Preparing .env ..."
if [[ ! -f "$APP_DIR/.env" ]]; then
  run_as_user "cp '$APP_DIR/.env.example' '$APP_DIR/.env'"
  echo "Created $APP_DIR/.env from template. Please edit API keys if needed."
fi

echo "==> Creating systemd service: $SERVICE_NAME"
TMP_SERVICE="$(mktemp)"
cat >"$TMP_SERVICE" <<EOF
[Unit]
Description=Word Learning Assistant (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$APP_DIR
EnvironmentFile=-$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn word_assistance.app:app --host 0.0.0.0 --port $APP_PORT
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

run_root install -m 0644 "$TMP_SERVICE" "/etc/systemd/system/$SERVICE_NAME.service"
rm -f "$TMP_SERVICE"

echo "==> Starting service..."
run_root systemctl daemon-reload
run_root systemctl enable --now "$SERVICE_NAME"
run_root systemctl restart "$SERVICE_NAME"

echo "==> Service status:"
run_root systemctl --no-pager --full status "$SERVICE_NAME" | sed -n '1,20p'
echo "==> Health check:"
curl -fsS "http://127.0.0.1:$APP_PORT/health" || true

echo
echo "Deployment done."
echo "App dir: $APP_DIR"
echo "Service: $SERVICE_NAME"
echo "URL: http://<your-server-ip>:$APP_PORT/"
echo "Update command: APP_DIR=$APP_DIR SERVICE_NAME=$SERVICE_NAME BRANCH=$BRANCH ./scripts/update_linux.sh"
