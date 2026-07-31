#!/usr/bin/env bash
set -Eeuo pipefail

# Deployment may be invoked from a root shell with a restrictive inherited
# umask. Tracked application files must remain readable by www-data.
umask 022

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT_DIR="$SCRIPT_ROOT"
LOCAL_HEALTH_URL="http://127.0.0.1:8080/health"
LOCAL_READY_URL="http://127.0.0.1:8080/ready"
LOCAL_STATUS_URL="http://127.0.0.1:8080/api/v1/status"
PUBLIC_HEALTH_URL="https://publish.toiletrage.co.uk/health"
PUBLIC_READY_URL="https://publish.toiletrage.co.uk/ready"
PUBLIC_STATUS_URL="https://publish.toiletrage.co.uk/api/v1/status"
API_SERVICE="book-system-api.service"
WORKER_SERVICE="book-system-worker.service"
FAILURE_UNIT="book-system-worker-failure@.service"
EXPECTED_COMMIT=""
SERVICES_STOPPED=0

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/deploy_server.sh \
    [--repo-root /opt/book-system] \
    --expected-commit <40-char reviewed commit>

The command fetches refs, verifies origin/main and the clean production checkout,
quiesces both services, fast-forwards only to the exact reviewed commit, audits
retained-job access as www-data, installs reviewed systemd units, and proves
service stability.

When the script is executed from a candidate staging directory, --repo-root
keeps script authority in the reviewed candidate while all repository mutation
targets the bounded production checkout.
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

on_exit() {
  local status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [[ $status -ne 0 && $SERVICES_STOPPED -eq 1 ]]; then
    echo "attempting-service-restart-after-deploy-failure=true" >&2
    systemctl start "$API_SERVICE" >/dev/null 2>&1 || true
    systemctl start "$WORKER_SERVICE" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

while (($#)); do
  case "$1" in
    --repo-root)
      ROOT_DIR="${2:-}"
      shift 2
      ;;
    --expected-commit)
      EXPECTED_COMMIT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
done

[[ "$(id -u)" -eq 0 ]] || fail "run as root"
[[ "$ROOT_DIR" == /* && "$ROOT_DIR" != "/" ]] || fail "repo root must be a bounded absolute path"
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit must be a full SHA-1"
[[ -d "$ROOT_DIR/.git" ]] || fail "repository is unavailable at $ROOT_DIR"
PYTHON="$ROOT_DIR/.venv/bin/python"
[[ -f "$ROOT_DIR/config/env" ]] || fail "missing $ROOT_DIR/config/env"
[[ -x "$PYTHON" ]] || fail "missing virtual-environment Python at $PYTHON"
[[ "$(stat -c '%a' "$ROOT_DIR/config/env")" == "600" ]] || fail "config/env mode is not 600"
[[ "$(stat -c '%U:%G' "$ROOT_DIR/config/env")" == "root:root" ]] || fail "config/env owner changed"

cd "$ROOT_DIR"
CONFIG_HASH_BEFORE="$(sha256sum config/env | awk '{print $1}')"

echo "===== BOOK SYSTEM EXACT DEPLOY ====="
echo "root=$ROOT_DIR"
echo "expected-commit=$EXPECTED_COMMIT"

echo
echo "===== REPOSITORY AUTHORITY ====="
git fetch --prune origin
[[ "$(git symbolic-ref --quiet --short HEAD)" == "main" ]] || fail "production checkout is not on main"
[[ "$(git rev-parse origin/main)" == "$EXPECTED_COMMIT" ]] || fail "origin/main is not the exact reviewed commit"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "production checkout is not clean"
CURRENT_COMMIT="$(git rev-parse HEAD)"
if [[ "$CURRENT_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  git merge-base --is-ancestor "$CURRENT_COMMIT" "$EXPECTED_COMMIT" || fail "expected commit is not a fast-forward"
fi

echo
echo "===== CURRENT RUNTIME COMPATIBILITY ====="
CURRENT_COMPATIBILITY_SCRIPT="$SCRIPT_ROOT/scripts/check_runtime_compatibility.py"
if [[ -f "$CURRENT_COMPATIBILITY_SCRIPT" ]]; then
  "$PYTHON" "$CURRENT_COMPATIBILITY_SCRIPT" --pandoc-only
else
  echo "current-runtime-compatibility-check=not-present-on-pre-correction-checkout"
fi

echo
echo "===== CURRENT SERVICE STATE ====="
systemctl is-active --quiet "$API_SERVICE" || fail "API service is not active before deployment"
systemctl is-active --quiet "$WORKER_SERVICE" || fail "worker service is not active before deployment"

echo
echo "===== QUIESCENT JOB STORE ====="
"$PYTHON" - "$ROOT_DIR/books/jobs" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
active = []
locks = []
for job in sorted(root.iterdir()):
    if not job.is_dir():
        continue
    if (job / ".lock").exists():
        locks.append(job.name)
    status_path = job / "status.json"
    if not status_path.is_file():
        continue
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"unreadable retained status record: {type(exc).__name__}")
    if status.get("status") in {"queued", "running"}:
        active.append(job.name)
if active or locks:
    raise SystemExit(f"active-or-locked jobs prevent deployment: active={len(active)} locks={len(locks)}")
print("active-or-locked-jobs=0")
PY

echo
echo "===== STOP AND QUIESCE SERVICES ====="
systemctl stop "$API_SERVICE" "$WORKER_SERVICE"
SERVICES_STOPPED=1
[[ "$(systemctl is-active "$API_SERVICE" || true)" == "inactive" ]] || fail "API service did not stop"
[[ "$(systemctl is-active "$WORKER_SERVICE" || true)" == "inactive" ]] || fail "worker service did not stop"

echo
echo "===== EXACT FAST-FORWARD ====="
if [[ "$CURRENT_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  git merge --ff-only "$EXPECTED_COMMIT"
fi
[[ "$(git rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] || fail "deployment did not reach exact commit"

echo
echo "===== NORMALISE TRACKED PERMISSIONS ====="
"$PYTHON" "$ROOT_DIR/scripts/normalise_tracked_permissions.py" --root "$ROOT_DIR"

echo
echo "===== CANDIDATE RUNTIME COMPATIBILITY ====="
"$PYTHON" "$ROOT_DIR/scripts/check_runtime_compatibility.py" \
  --fix-git-head-readability \
  --expected-commit "$EXPECTED_COMMIT"
runuser -u www-data -- \
  "$PYTHON" "$ROOT_DIR/scripts/check_runtime_compatibility.py" \
  --expected-commit "$EXPECTED_COMMIT"
echo "candidate-runtime-compatibility=pass"

echo
echo "===== SERVICE SOURCE READABILITY ====="
for source in \
  app/services/job_queue.py \
  app/services/pandoc_capability.py \
  app/services/readiness.py \
  app/services/readiness_guard.py \
  app/services/worker.py \
  app/pipeline/run_pipeline.py \
  app/utils/atomic_files.py \
  scripts/audit_job_service_access.py \
  scripts/check_runtime_compatibility.py; do
  runuser -u www-data -- test -r "$ROOT_DIR/$source" || fail "www-data cannot read $source"
done
echo "service-source-readability=pass"

"$PYTHON" "$ROOT_DIR/scripts/audit_job_service_access.py" \
  --jobs-root "$ROOT_DIR/books/jobs" \
  --service-user www-data
echo "service-account-job-audit=pass"

echo
echo "===== INSTALL REVIEWED SYSTEMD UNITS ====="
install -m 0644 "$ROOT_DIR/deploy/systemd/book-system-api.service" "/etc/systemd/system/$API_SERVICE"
install -m 0644 "$ROOT_DIR/deploy/systemd/book-system-worker.service" "/etc/systemd/system/$WORKER_SERVICE"
install -m 0644 "$ROOT_DIR/deploy/systemd/book-system-worker-failure@.service" "/etc/systemd/system/$FAILURE_UNIT"
systemctl daemon-reload
systemctl enable "$API_SERVICE" "$WORKER_SERVICE" >/dev/null

[[ "$(systemctl show "$WORKER_SERVICE" --property=StartLimitBurst --value)" == "3" ]] || fail "worker StartLimitBurst was not installed"
START_LIMIT_INTERVAL="$(systemctl show "$WORKER_SERVICE" --property=StartLimitIntervalUSec --value)"
[[ "$START_LIMIT_INTERVAL" =~ ^(5min|300s|300000000us)$ ]] || fail "worker start-limit interval is unexpected: $START_LIMIT_INTERVAL"
[[ "$(systemctl show "$WORKER_SERVICE" --property=OnFailure --value)" == *"book-system-worker-failure@"* ]] || fail "worker failure alarm was not installed"
echo "worker-restart-guard=pass"

echo
echo "===== RECENT COMMITS ====="
git log --oneline -3

echo
echo "===== PYTHON COMPILE ====="
"$PYTHON" -m compileall -q app scripts

echo
echo "===== START SERVICES ====="
systemctl reset-failed "$WORKER_SERVICE" || true
systemctl start "$API_SERVICE"
systemctl start "$WORKER_SERVICE"
SERVICES_STOPPED=0

echo
echo "===== SERVICE STATE ====="
systemctl is-active "$API_SERVICE"
systemctl is-active "$WORKER_SERVICE"

echo
echo "===== WAIT FOR LOCAL API LIVENESS ====="
for i in {1..30}; do
  if curl -fsS "$LOCAL_HEALTH_URL" >/dev/null 2>&1; then
    echo "API process is alive"
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    systemctl status "$API_SERVICE" --no-pager -l || true
    journalctl -u "$API_SERVICE" -n 80 --no-pager || true
    fail "API liveness did not pass after 30 seconds"
  fi
  sleep 1
done

echo
echo "===== WAIT FOR LOCAL READINESS ====="
for i in {1..30}; do
  if curl -fsS "$LOCAL_READY_URL" >/dev/null 2>&1; then
    echo "Publishing service is ready"
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    curl -sS "$LOCAL_READY_URL" || true
    systemctl status "$WORKER_SERVICE" --no-pager -l || true
    journalctl -u "$WORKER_SERVICE" -n 80 --no-pager || true
    fail "publishing readiness did not pass after 30 seconds"
  fi
  sleep 1
done

echo
echo "===== WORKER STABILITY WINDOW ====="
PID_BEFORE="$(systemctl show "$WORKER_SERVICE" --property=MainPID --value)"
RESTARTS_BEFORE="$(systemctl show "$WORKER_SERVICE" --property=NRestarts --value)"
[[ "$PID_BEFORE" =~ ^[1-9][0-9]*$ ]] || fail "worker has no live PID"
sleep 20
systemctl is-active --quiet "$WORKER_SERVICE" || fail "worker did not remain active"
PID_AFTER="$(systemctl show "$WORKER_SERVICE" --property=MainPID --value)"
RESTARTS_AFTER="$(systemctl show "$WORKER_SERVICE" --property=NRestarts --value)"
[[ "$PID_AFTER" == "$PID_BEFORE" ]] || fail "worker PID changed during stability window"
[[ "$RESTARTS_AFTER" == "$RESTARTS_BEFORE" ]] || fail "worker restart count increased"
echo "worker-main-pid=$PID_AFTER"
echo "worker-restarts=$RESTARTS_AFTER"

echo
echo "===== LOCAL HEALTH ====="
curl -fsS "$LOCAL_HEALTH_URL"; echo

echo
echo "===== LOCAL READINESS ====="
curl -fsS "$LOCAL_READY_URL"; echo

echo
echo "===== LOCAL STATUS ====="
curl -fsS "$LOCAL_STATUS_URL"; echo

echo
echo "===== PUBLIC HEALTH ====="
curl -fsS -4 "$PUBLIC_HEALTH_URL"; echo

echo
echo "===== PUBLIC READINESS ====="
curl -fsS -4 "$PUBLIC_READY_URL"; echo

echo
echo "===== PUBLIC STATUS ====="
curl -fsS -4 "$PUBLIC_STATUS_URL"; echo

[[ "$(sha256sum config/env | awk '{print $1}')" == "$CONFIG_HASH_BEFORE" ]] || fail "config/env changed during deployment"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] || fail "final deployed commit changed"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "deployment left repository changes"

echo
echo "===== DEPLOY COMPLETE ====="
echo "deployed-commit=$EXPECTED_COMMIT"
echo "config-hash=$CONFIG_HASH_BEFORE"
echo "service-account-job-audit=pass"
echo "worker-restart-guard=pass"
echo "worker-stability=pass"
echo "runtime-compatibility=pass"
