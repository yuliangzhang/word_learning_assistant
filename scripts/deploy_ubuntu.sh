#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ubuntu friendly defaults. You can override via env vars:
# REPO_URL / BRANCH / APP_DIR / APP_PORT / SERVICE_NAME / APP_USER / APP_GROUP / PYTHON_BIN
exec "$SCRIPT_DIR/deploy_linux.sh" "$@"
