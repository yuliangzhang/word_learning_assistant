#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:$PATH"

cleanup() {
  ./scripts/dev_down.sh >/dev/null 2>&1 || true
}
trap cleanup EXIT

./scripts/dev_up.sh

if [[ ! -d "$ROOT_DIR/node_modules/@playwright/test" ]]; then
  npm install --save-dev @playwright/test
fi

npx playwright install chromium
npx playwright test -c e2e/playwright.config.js
