#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MODE=""
SKIP_INSTALL=0

usage() {
  echo "Usage: $0 --local|--docker [--skip-install]"
  exit 1
}

ensure_playwright() {
  if [[ $SKIP_INSTALL -eq 0 ]]; then
    python -m playwright install chromium >/dev/null
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      MODE="local"
      ;;
    --docker)
      MODE="docker"
      ;;
    --skip-install)
      SKIP_INSTALL=1
      ;;
    *)
      usage
      ;;
  esac
  shift
done

[[ -z "$MODE" ]] && usage

if [[ "$MODE" == "local" ]]; then
  cd "$ROOT"
  ensure_playwright
  python -m pytest tests/test_pwa_assets.py
  EXTRA=""
  if [[ $SKIP_INSTALL -eq 1 ]]; then
    EXTRA="--skip-install"
  fi
  python scripts/run_e2e.py --suite smoke ${EXTRA}
  exit 0
fi

if [[ "$MODE" == "docker" ]]; then
  cd "$ROOT"
  ensure_playwright

  TEST_PORT="${PWA_TEST_PORT:-8012}"
  RUNTIME="$ROOT/tmp/pwa-docker"
  DATA_ROOT="$RUNTIME/data"
  mkdir -p "$DATA_ROOT/sources"
  rm -rf "$DATA_ROOT/sources/demo"
  cp -r "$ROOT/testdata/sources/demo" "$DATA_ROOT/sources/demo"

  export DATA_HOST_PATH="$DATA_ROOT"
  export DATA_CONTAINER_PATH="/data"
  export INDEX_ROOTS="/data/sources/demo:demo"
  export APP_SECRET="${APP_SECRET:-pwa-docker-secret}"
  export ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
  export TZ="${TZ:-UTC}"
  export LOG_DIR="/app/logs"
  export APP_HTTP_PORT="$TEST_PORT"
  export CONTAINER_NAME="index-search-web-pwa-test"

  PROJECT="index-search-pwa-test"
  docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" up -d --build web

  BASE_URL="http://localhost:${TEST_PORT}"
  READY=0
  for _ in {1..40}; do
    if curl -skf "$BASE_URL/manifest.webmanifest" >/dev/null; then
      READY=1
      break
    fi
    sleep 1
  done

  if [[ $READY -ne 1 ]]; then
    echo "Container nicht bereit auf $BASE_URL"
    docker compose -p "$PROJECT" logs --tail=80 web || true
    docker compose -p "$PROJECT" down
    exit 1
  fi

  APP_BASE_URL="$BASE_URL" APP_SECRET="$APP_SECRET" E2E_EXTERNAL=1 \
    pytest -m "e2e and pwa" tests/test_pwa_ui.py

  docker compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" down
  exit 0
fi

usage
