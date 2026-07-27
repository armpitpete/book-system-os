#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="${BOOK_SYSTEM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON="$ROOT_DIR/.venv/bin/python"
JOBS_ROOT="$ROOT_DIR/books/jobs"
LOCAL_BASE="http://127.0.0.1:8080"
PUBLIC_BASE="https://publish.toiletrage.co.uk"
API_SERVICE="book-system-api.service"
WORKER_SERVICE="book-system-worker.service"

EXPECTED_CURRENT=""
TARGET_COMMIT=""
JOB_ID=""
EVIDENCE_DIR=""
CONFIRM=""
WORKER_STOPPED=0
PASSED=0

usage() {
    cat <<'EOF'
Usage:
  sudo bash scripts/h09_live_rehearsal.sh \
    --expected-current <40-char merged H-09 commit> \
    --target <40-char accepted H-08 commit> \
    --job-id <completed production job> \
    --evidence-dir <new absolute private directory> \
    --confirm exact-h09-rehearsal

Run this command through nohup or another operator-controlled detached session.
The runner stops the worker only long enough to prove readiness failure, restores
it, and then invokes the guarded exact-commit rollback utility.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --expected-current)
            EXPECTED_CURRENT="${2:-}"
            shift 2
            ;;
        --target)
            TARGET_COMMIT="${2:-}"
            shift 2
            ;;
        --job-id)
            JOB_ID="${2:-}"
            shift 2
            ;;
        --evidence-dir)
            EVIDENCE_DIR="${2:-}"
            shift 2
            ;;
        --confirm)
            CONFIRM="${2:-}"
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
[[ "$CONFIRM" == "exact-h09-rehearsal" ]] || fail "missing exact rehearsal confirmation"
[[ "$EXPECTED_CURRENT" =~ ^[0-9a-f]{40}$ ]] || fail "expected current commit must be a full SHA-1"
[[ "$TARGET_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "target commit must be a full SHA-1"
[[ "$EXPECTED_CURRENT" != "$TARGET_COMMIT" ]] || fail "candidate and target commits are identical"
[[ -n "$JOB_ID" && "$JOB_ID" != *"/"* && "$JOB_ID" != *"\\"* && "$JOB_ID" != *".."* ]] || fail "unsafe job id"
[[ "$EVIDENCE_DIR" == /* ]] || fail "evidence directory must be absolute"
[[ "$EVIDENCE_DIR" != "$ROOT_DIR"/* ]] || fail "evidence directory must be outside the repository"
[[ -x "$PYTHON" ]] || fail "missing virtual-environment Python"

PRIVATE_DIR="$EVIDENCE_DIR/private"

if [[ "${H09_REHEARSAL_COPIED:-0}" != "1" ]]; then
    [[ ! -e "$EVIDENCE_DIR" ]] || fail "evidence directory already exists"
    mkdir -p "$PRIVATE_DIR"
    chmod 0700 "$EVIDENCE_DIR" "$PRIVATE_DIR"
    cp "$ROOT_DIR/scripts/h09_live_rehearsal.sh" "$PRIVATE_DIR/h09_live_rehearsal.sh"
    cp "$ROOT_DIR/scripts/audit_job_service_access.py" "$PRIVATE_DIR/audit_job_service_access.py"
    cp "$ROOT_DIR/scripts/rollback_server.sh" "$PRIVATE_DIR/rollback_server.sh"
    cp "$ROOT_DIR/scripts/snapshot_job_integrity.py" "$PRIVATE_DIR/snapshot_job_integrity.py"
    cp "$ROOT_DIR/scripts/verify_job_downloads.py" "$PRIVATE_DIR/verify_job_downloads.py"
    chmod 0700 "$PRIVATE_DIR"/*
    sha256sum "$PRIVATE_DIR"/* > "$EVIDENCE_DIR/rehearsal-scripts.sha256"
    chmod 0600 "$EVIDENCE_DIR/rehearsal-scripts.sha256"
    exec env \
        BOOK_SYSTEM_ROOT="$ROOT_DIR" \
        H09_REHEARSAL_COPIED=1 \
        bash "$PRIVATE_DIR/h09_live_rehearsal.sh" \
        --expected-current "$EXPECTED_CURRENT" \
        --target "$TARGET_COMMIT" \
        --job-id "$JOB_ID" \
        --evidence-dir "$EVIDENCE_DIR" \
        --confirm exact-h09-rehearsal
fi

[[ -d "$PRIVATE_DIR" ]] || fail "copied rehearsal directory is missing"
exec > >(tee -a "$EVIDENCE_DIR/rehearsal.log") 2>&1

write_result() {
    local result="$1"
    local stage="$2"
    "$PYTHON" - "$EVIDENCE_DIR/result.json" "$result" "$stage" "$EXPECTED_CURRENT" "$TARGET_COMMIT" "$JOB_ID" <<'PY'
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
record = {
    "version": 1,
    "result": sys.argv[2],
    "stage": sys.argv[3],
    "candidate_commit": sys.argv[4],
    "target_commit": sys.argv[5],
    "job_id": sys.argv[6],
    "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY
}

CURRENT_STAGE="initialisation"
on_exit() {
    local status=$?
    trap - EXIT HUP INT TERM
    set +e
    if [[ $status -ne 0 ]]; then
        if [[ $WORKER_STOPPED -eq 1 ]]; then
            systemctl start "$WORKER_SERVICE" >/dev/null 2>&1 || true
        fi
        write_result "FAIL" "$CURRENT_STAGE" || true
        echo
        echo "h09-live-rehearsal=FAIL"
        echo "failure-stage=$CURRENT_STAGE"
        echo "evidence=$EVIDENCE_DIR"
    elif [[ $PASSED -ne 1 ]]; then
        write_result "FAIL" "missing-pass-marker" || true
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'CURRENT_STAGE="signal-HUP"; exit 129' HUP
trap 'CURRENT_STAGE="signal-INT"; exit 130' INT
trap 'CURRENT_STAGE="signal-TERM"; exit 143' TERM

wait_http_code() {
    local label="$1"
    local expected="$2"
    local url="$3"
    local output="$4"
    local ipv4="${5:-0}"
    local code
    for _attempt in $(seq 1 45); do
        if [[ "$ipv4" == "1" ]]; then
            code="$(curl -sS -4 -o "$output" -w '%{http_code}' "$url" || true)"
        else
            code="$(curl -sS -o "$output" -w '%{http_code}' "$url" || true)"
        fi
        if [[ "$code" == "$expected" ]]; then
            echo "$label=http-$code"
            return 0
        fi
        sleep 1
    done
    fail "$label returned HTTP $code; expected $expected"
}

verify_worker_guard() {
    local burst interval on_failure
    burst="$(systemctl show "$WORKER_SERVICE" --property=StartLimitBurst --value)"
    interval="$(systemctl show "$WORKER_SERVICE" --property=StartLimitIntervalUSec --value)"
    on_failure="$(systemctl show "$WORKER_SERVICE" --property=OnFailure --value)"
    [[ "$burst" == "3" ]] || fail "worker StartLimitBurst is $burst, expected 3"
    [[ "$interval" =~ ^(5min|300s|300000000us)$ ]] || fail "worker start-limit interval is unexpected: $interval"
    [[ "$on_failure" == *"book-system-worker-failure@"* ]] || fail "worker OnFailure alarm is missing"
    systemctl cat book-system-worker-failure@.service > "$EVIDENCE_DIR/worker-failure-alarm.unit.txt"
    echo "worker-restart-limit=3-per-5min"
    echo "worker-onfailure-alarm=pass"
}

verify_worker_stability() {
    local label="$1"
    local pid_before pid_after restarts_before restarts_after
    systemctl is-active --quiet "$WORKER_SERVICE" || fail "$label worker is not active"
    pid_before="$(systemctl show "$WORKER_SERVICE" --property=MainPID --value)"
    restarts_before="$(systemctl show "$WORKER_SERVICE" --property=NRestarts --value)"
    [[ "$pid_before" =~ ^[1-9][0-9]*$ ]] || fail "$label worker has no live PID"
    sleep 20
    systemctl is-active --quiet "$WORKER_SERVICE" || fail "$label worker did not remain active"
    pid_after="$(systemctl show "$WORKER_SERVICE" --property=MainPID --value)"
    restarts_after="$(systemctl show "$WORKER_SERVICE" --property=NRestarts --value)"
    [[ "$pid_after" == "$pid_before" ]] || fail "$label worker PID changed"
    [[ "$restarts_after" == "$restarts_before" ]] || fail "$label worker restart count increased"
    echo "$label-worker-pid=$pid_after"
    echo "$label-worker-restarts=$restarts_after"
}

verify_readiness_failure() {
    "$PYTHON" - "$EVIDENCE_DIR/stopped-local-health.json" "$EVIDENCE_DIR/stopped-local-ready.json" "$EVIDENCE_DIR/stopped-public-ready.json" "$ROOT_DIR" "$JOB_ID" <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path

local_health = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
local_ready = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
public_ready = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
root = sys.argv[4]
job_id = sys.argv[5]
assert local_health == {"status": "ok"}, local_health
for report in (local_ready, public_ready):
    assert report["ready"] is False, report
    assert report["checks"]["worker"]["status"] == "fail", report
    encoded = json.dumps(report, sort_keys=True)
    assert root not in encoded
    assert job_id not in encoded
print("stopped-worker-readiness-sanitised=pass")
PY
}

CURRENT_STAGE="repository-preconditions"
cd "$ROOT_DIR"
git fetch --prune origin
[[ "$(git rev-parse HEAD)" == "$EXPECTED_CURRENT" ]] || fail "deployed HEAD changed"
[[ "$(git rev-parse origin/main)" == "$EXPECTED_CURRENT" ]] || fail "origin/main is not the exact candidate"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "repository is not clean"
git cat-file -e "$TARGET_COMMIT^{commit}"
git merge-base --is-ancestor "$TARGET_COMMIT" "$EXPECTED_CURRENT" || fail "target is not an ancestor of candidate"
[[ "$(stat -c '%a' config/env)" == "600" ]] || fail "config/env mode changed"
CONFIG_HASH="$(sha256sum config/env | awk '{print $1}')"
echo "candidate=$EXPECTED_CURRENT"
echo "target=$TARGET_COMMIT"
echo "job-id=$JOB_ID"
echo "config-hash=$CONFIG_HASH"

CURRENT_STAGE="service-account-access-audit"
"$PYTHON" "$PRIVATE_DIR/audit_job_service_access.py" \
    --jobs-root "$JOBS_ROOT" \
    --service-user www-data \
    --output "$EVIDENCE_DIR/service-access-before.json"
echo "service-account-job-audit-before=pass"

CURRENT_STAGE="candidate-service-state"
systemctl is-active --quiet "$API_SERVICE" || fail "API service is not active"
systemctl is-active --quiet "$WORKER_SERVICE" || fail "worker service is not active"
verify_worker_guard
verify_worker_stability "candidate"
wait_http_code "candidate-local-health" 200 "$LOCAL_BASE/health" "$EVIDENCE_DIR/candidate-local-health.json"
wait_http_code "candidate-local-readiness" 200 "$LOCAL_BASE/ready" "$EVIDENCE_DIR/candidate-local-ready.json"
wait_http_code "candidate-public-health" 200 "$PUBLIC_BASE/health" "$EVIDENCE_DIR/candidate-public-health.json" 1
wait_http_code "candidate-public-readiness" 200 "$PUBLIC_BASE/ready" "$EVIDENCE_DIR/candidate-public-ready.json" 1

CURRENT_STAGE="stopped-worker-readiness-proof"
systemctl stop "$WORKER_SERVICE"
WORKER_STOPPED=1
wait_http_code "stopped-local-health" 200 "$LOCAL_BASE/health" "$EVIDENCE_DIR/stopped-local-health.json"
wait_http_code "stopped-local-readiness" 503 "$LOCAL_BASE/ready" "$EVIDENCE_DIR/stopped-local-ready.json"
wait_http_code "stopped-public-readiness" 503 "$PUBLIC_BASE/ready" "$EVIDENCE_DIR/stopped-public-ready.json" 1
verify_readiness_failure
echo "stopped-worker-detection=pass"

CURRENT_STAGE="worker-restoration-before-rollback"
systemctl reset-failed "$WORKER_SERVICE" || true
systemctl start "$WORKER_SERVICE"
WORKER_STOPPED=0
wait_http_code "restored-local-readiness" 200 "$LOCAL_BASE/ready" "$EVIDENCE_DIR/restored-local-ready.json"
wait_http_code "restored-public-readiness" 200 "$PUBLIC_BASE/ready" "$EVIDENCE_DIR/restored-public-ready.json" 1
verify_worker_stability "restored"

CURRENT_STAGE="exact-rollback"
ROLLBACK_EVIDENCE="$EVIDENCE_DIR/rollback"
env BOOK_SYSTEM_ROOT="$ROOT_DIR" bash "$ROOT_DIR/scripts/rollback_server.sh" \
    --expected-current "$EXPECTED_CURRENT" \
    --target "$TARGET_COMMIT" \
    --job-id "$JOB_ID" \
    --evidence-dir "$ROLLBACK_EVIDENCE" \
    --confirm exact-rollback

CURRENT_STAGE="post-rollback-verification"
[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || fail "rollback did not reach exact target"
[[ "$(sha256sum "$ROOT_DIR/config/env" | awk '{print $1}')" == "$CONFIG_HASH" ]] || fail "config/env changed"
systemctl is-active --quiet "$API_SERVICE" || fail "API is inactive after rollback"
systemctl is-active --quiet "$WORKER_SERVICE" || fail "worker is inactive after rollback"
"$PYTHON" "$PRIVATE_DIR/audit_job_service_access.py" \
    --jobs-root "$JOBS_ROOT" \
    --service-user www-data \
    --output "$EVIDENCE_DIR/service-access-after.json"
cmp -s "$EVIDENCE_DIR/service-access-before.json" "$EVIDENCE_DIR/service-access-after.json" || fail "service-access report changed"
verify_worker_guard
verify_worker_stability "rollback-target"
wait_http_code "rollback-local-health" 200 "$LOCAL_BASE/health" "$EVIDENCE_DIR/rollback-local-health.json"
wait_http_code "rollback-local-readiness" 200 "$LOCAL_BASE/ready" "$EVIDENCE_DIR/rollback-local-ready.json"
wait_http_code "rollback-public-health" 200 "$PUBLIC_BASE/health" "$EVIDENCE_DIR/rollback-public-health.json" 1
wait_http_code "rollback-public-readiness" 200 "$PUBLIC_BASE/ready" "$EVIDENCE_DIR/rollback-public-ready.json" 1

CURRENT_STAGE="complete"
write_result "PASS" "$CURRENT_STAGE"
PASSED=1
chmod 0600 "$EVIDENCE_DIR"/*.json "$EVIDENCE_DIR"/*.log "$EVIDENCE_DIR"/*.txt "$EVIDENCE_DIR"/*.sha256 2>/dev/null || true

echo
echo "===== H-09 LIVE REHEARSAL RESULT ====="
echo "h09-live-rehearsal=PASS"
echo "candidate-commit=$EXPECTED_CURRENT"
echo "restored-commit=$TARGET_COMMIT"
echo "job-id=$JOB_ID"
echo "evidence=$EVIDENCE_DIR"
echo "next-protected-action=review evidence, then separately redeploy exact candidate"
