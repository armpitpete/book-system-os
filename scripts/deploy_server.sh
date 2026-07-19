#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
LOCAL_HEALTH_URL="http://127.0.0.1:8080/health"
LOCAL_STATUS_URL="http://127.0.0.1:8080/api/v1/status"
PUBLIC_HEALTH_URL="https://publish.toiletrage.co.uk/health"
PUBLIC_STATUS_URL="https://publish.toiletrage.co.uk/api/v1/status"

cd "$ROOT_DIR"

echo "===== BOOK SYSTEM DEPLOY ====="
echo "Root: $ROOT_DIR"

if [ ! -f "$ROOT_DIR/config/env" ]; then
  echo "ERROR: missing $ROOT_DIR/config/env"
  exit 1
fi

if [ ! -x "$PYTHON" ]; then
  echo "ERROR: missing virtual-environment Python at $PYTHON"
  exit 1
fi

echo
echo "===== GIT PULL ====="
git pull --ff-only

echo
echo "===== RECENT COMMITS ====="
git log --oneline -3

echo
echo "===== PYTHON COMPILE ====="
"$PYTHON" -m compileall -q app scripts

echo
echo "===== RESTART SERVICES ====="
systemctl restart book-system-api.service
systemctl restart book-system-worker.service

echo
echo "===== SERVICE STATE ====="
systemctl is-active book-system-api.service
systemctl is-active book-system-worker.service

echo
echo "===== WAIT FOR LOCAL API ====="
for i in {1..30}; do
  if curl -fsS "$LOCAL_HEALTH_URL" >/dev/null 2>&1; then
    echo "API is ready"
    break
  fi

  if [ "$i" -eq 30 ]; then
    echo "ERROR: API did not become ready after 30 seconds"
    echo
    systemctl status book-system-api.service --no-pager -l || true
    echo
    journalctl -u book-system-api.service -n 80 --no-pager || true
    exit 1
  fi

  echo "Waiting for API..."
  sleep 1
done

echo
echo "===== LOCAL HEALTH ====="
curl -fsS "$LOCAL_HEALTH_URL"
echo

echo
echo "===== LOCAL STATUS ====="
curl -fsS "$LOCAL_STATUS_URL"
echo

echo
echo "===== PUBLIC HEALTH ====="
curl -fsS -4 "$PUBLIC_HEALTH_URL"
echo

echo
echo "===== PUBLIC STATUS ====="
curl -fsS -4 "$PUBLIC_STATUS_URL"
echo

echo
echo "===== DEPLOY COMPLETE ====="
