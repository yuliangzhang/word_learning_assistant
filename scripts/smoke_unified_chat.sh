#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  ./scripts/dev_down.sh >/dev/null 2>&1 || true
}
trap cleanup EXIT

./scripts/dev_up.sh

echo
echo "== OpenClaw status =="
curl -fsS "http://127.0.0.1:8000/api/openclaw/status"
echo

echo
echo "== Unified chat smoke =="
curl -fsS -X POST "http://127.0.0.1:8000/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"user_id":2,"message":"帮我开始今天任务"}'
echo

echo
echo "smoke check passed"
