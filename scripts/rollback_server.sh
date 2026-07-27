#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT_DIR/.venv/bin/python"
LOCAL_BASE="http://127.0.0.1:8080"
PUBLIC_BASE="https://publish.toiletrage.co.uk"
API_SERVICE="book-system-api.service"
WORKER_SERVICE="book-system-worker.service"

TARGET_COMMIT=""
EXPECTED_CURRENT=""
JOB_ID=""
EVIDENCE_DIR=""
CONFIRM=""
SERVICES_STOPPED=0
STARTED_AT="$(date +%s)"

usage() {
    cat <<'EOF'
Usage:
  sudo bash scripts/rollback_server.sh \
    --expected-current <40-char commit> \
    --target <40-char earlier commit> \
    --job-id <completed job id> \
    --evidence-dir <new absolute directory outside the repository> \
    --confirm exact-rollback

The command rewinds only the tracked application checkout. It refuses to run
unless persistent data is untracked, services can be quiesced, and the selected
completed job can be snapshotted before the reset.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --target)
            TARGET_COMMIT="${2:-}"
            shift 2
            ;;
        --expected-current)
            EXPECTED_CURRENT="${2:-}"
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
        --local-base)
            LOCAL_BASE="${2:-}"
            shift 2
            ;;
        --public-base)
            PUBLIC_BASE="${2:-}"
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
[[ "$CONFIRM" == "exact-rollback" ]] || fail "missing exact rollback confirmation"
[[ "$EXPECTED_CURRENT" =~ ^[0-9a-f]{40}$ ]] || fail "expected current commit must be a full SHA-1"
[[ "$TARGET_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "target commit must be a full SHA-1"
[[ -n "$JOB_ID" && "$JOB_ID" != *"/"* && "$JOB_ID" != *"\\"* && "$JOB_ID" != *".."* ]] || fail "unsafe job id"
[[ "$EVIDENCE_DIR" == /* ]] || fail "evidence directory must be absolute"
[[ "$EVIDENCE_DIR" != "$ROOT_DIR"/* ]] || fail "evidence directory must be outside the repository"
[[ ! -e "$EVIDENCE_DIR" ]] || fail "evidence directory already exists"
[[ -x "$PYTHON" ]] || fail "missing virtual-environment Python"
[[ -f "$ROOT_DIR/config/env" ]] || fail "missing runtime environment file"
[[ "$(stat -c '%a' "$ROOT_DIR/config/env")" == "600" ]] || fail "config/env mode is not 600"
[[ "$(stat -c '%U:%G' "$ROOT_DIR/config/env")" == "root:root" ]] || fail "config/env owner changed"

mkdir -p "$EVIDENCE_DIR"
chmod 0700 "$EVIDENCE_DIR"
exec > >(tee -a "$EVIDENCE_DIR/rollback.log") 2>&1

on_exit() {
    status=$?
    if [[ $status -ne 0 ]]; then
        echo
        echo "rollback-result=FAIL"
        echo "rollback-exit=$status"
        if [[ $SERVICES_STOPPED -eq 1 ]]; then
            echo "attempting-service-restart-after-failure=true"
            systemctl start "$API_SERVICE" || true
            systemctl start "$WORKER_SERVICE" || true
            systemctl is-active "$API_SERVICE" || true
            systemctl is-active "$WORKER_SERVICE" || true
        fi
    fi
}
trap on_exit EXIT

cd "$ROOT_DIR"
cp scripts/rollback_server.sh "$EVIDENCE_DIR/rollback_server.sh"
cp scripts/snapshot_job_integrity.py "$EVIDENCE_DIR/snapshot_job_integrity.py"
cp scripts/verify_job_downloads.py "$EVIDENCE_DIR/verify_job_downloads.py"
cp scripts/verify_operational_logs.py "$EVIDENCE_DIR/verify_operational_logs.py"
chmod 0700 \
    "$EVIDENCE_DIR/rollback_server.sh" \
    "$EVIDENCE_DIR/snapshot_job_integrity.py" \
    "$EVIDENCE_DIR/verify_job_downloads.py" \
    "$EVIDENCE_DIR/verify_operational_logs.py"

snapshot_store() {
    local output="$1"
    "$PYTHON" - "$ROOT_DIR/books/jobs" "$output" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2])
files = {}
for path in sorted(root.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"job-store-symlink: {path.relative_to(root)}")
    if path.is_dir() or path.name == ".lock":
        continue
    if not path.is_file():
        raise SystemExit(f"job-store-non-regular: {path.relative_to(root)}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    files[path.relative_to(root).as_posix()] = {
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
fd = os.open(output, flags, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump({"version": 1, "files": files}, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(f"job-store-files={len(files)}")
PY
}

snapshot_logs() {
    local output="$1"
    "$PYTHON" - "$ROOT_DIR/logs" "$output" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
output = Path(sys.argv[2])
files = {}
for path in sorted(root.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"log-symlink: {path.relative_to(root)}")
    if path.is_dir():
        continue
    if not path.is_file():
        raise SystemExit(f"log-non-regular: {path.relative_to(root)}")
    payload = path.read_bytes()
    files[path.relative_to(root).as_posix()] = {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump({"version": 1, "files": files}, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(f"operational-log-files={len(files)}")
PY
}

wait_url() {
    local label="$1"
    local url="$2"
    local ipv4="${3:-0}"
    for attempt in {1..45}; do
        if [[ "$ipv4" == "1" ]]; then
            if curl -fsS -4 "$url" >/dev/null 2>&1; then
                echo "$label=pass"
                return 0
            fi
        elif curl -fsS "$url" >/dev/null 2>&1; then
            echo "$label=pass"
            return 0
        fi
        sleep 1
    done
    fail "$label did not pass: $url"
}

echo "===== H-09 EXACT-COMMIT ROLLBACK ====="
echo "timestamp=$(date -u +%Y%m%dT%H%M%SZ)"
echo "root=$ROOT_DIR"
echo "expected-current=$EXPECTED_CURRENT"
echo "target=$TARGET_COMMIT"
echo "job-id=$JOB_ID"
echo "evidence=$EVIDENCE_DIR"

echo
echo "===== REPOSITORY PRECONDITIONS ====="
git fetch --prune origin
CURRENT_COMMIT="$(git rev-parse HEAD)"
[[ "$CURRENT_COMMIT" == "$EXPECTED_CURRENT" ]] || fail "deployed head changed: $CURRENT_COMMIT"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "repository changes or untracked application files are present"
git cat-file -e "$TARGET_COMMIT^{commit}"
[[ "$(git rev-parse "$TARGET_COMMIT^{commit}")" == "$TARGET_COMMIT" ]] || fail "target did not resolve exactly"
git merge-base --is-ancestor "$TARGET_COMMIT" "$EXPECTED_CURRENT" || fail "target is not an ancestor of current commit"
[[ "$TARGET_COMMIT" != "$EXPECTED_CURRENT" ]] || fail "target equals current commit"
for required in \
    scripts/normalise_tracked_permissions.py \
    app/api/app.py \
    app/services/worker.py \
    deploy/systemd/book-system-api.service \
    deploy/systemd/book-system-worker.service; do
    git cat-file -e "$TARGET_COMMIT:$required" || fail "target is missing required path: $required"
done
TRACKED_PERSISTENT="$(git ls-files -- config/env books/jobs logs | grep -vE '(^|/)\.gitkeep$' || true)"
[[ -z "$TRACKED_PERSISTENT" ]] || fail "persistent runtime paths contain tracked files"
echo "repository-preconditions=pass"

echo
echo "===== INSTALLED SERVICE-UNIT PRECONDITIONS ====="
for service in "$API_SERVICE" "$WORKER_SERVICE"; do
    [[ "$(systemctl show --property=User --value "$service")" == "www-data" ]] || fail "$service user changed"
    [[ "$(systemctl show --property=Group --value "$service")" == "www-data" ]] || fail "$service group changed"
    [[ "$(systemctl show --property=WorkingDirectory --value "$service")" == "$ROOT_DIR" ]] || fail "$service working directory changed"
    [[ "$(systemctl show --property=NoNewPrivileges --value "$service")" == "yes" ]] || fail "$service no-new-privileges guard changed"
    [[ "$(systemctl show --property=ProtectSystem --value "$service")" == "strict" ]] || fail "$service protect-system guard changed"

    ENVIRONMENT_FILES="$(systemctl show --property=EnvironmentFiles --value "$service")"
    EXEC_START="$(systemctl show --property=ExecStart --value "$service")"
    READ_WRITE_PATHS="$(systemctl show --property=ReadWritePaths --value "$service")"
    FRAGMENT_PATH="$(systemctl show --property=FragmentPath --value "$service")"

    [[ "$ENVIRONMENT_FILES" == *"$ROOT_DIR/config/env"* ]] || fail "$service effective environment file changed"
    [[ "$EXEC_START" == *"$ROOT_DIR/"* ]] || fail "$service effective executable path changed"
    [[ "$READ_WRITE_PATHS" == *"$ROOT_DIR/books"* ]] || fail "$service effective books write boundary changed"
    [[ "$READ_WRITE_PATHS" == *"$ROOT_DIR/logs"* ]] || fail "$service effective logs write boundary changed"
    [[ -f "$FRAGMENT_PATH" ]] || fail "$service fragment path is unavailable"

    systemctl cat "$service" > "$EVIDENCE_DIR/${service}.unit.txt"
    systemctl show "$service" \
        --property=User,Group,WorkingDirectory,EnvironmentFiles,ExecStart,ReadWritePaths,NoNewPrivileges,ProtectSystem,FragmentPath \
        > "$EVIDENCE_DIR/${service}.effective.txt"
done
echo "installed-service-units=pass"

echo
echo "===== STOP AND QUIESCE SERVICES ====="
systemctl stop "$API_SERVICE" "$WORKER_SERVICE"
SERVICES_STOPPED=1
[[ "$(systemctl is-active "$API_SERVICE" || true)" == "inactive" ]] || fail "API did not stop"
[[ "$(systemctl is-active "$WORKER_SERVICE" || true)" == "inactive" ]] || fail "worker did not stop"
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
    lock = job / ".lock"
    if lock.exists():
        locks.append(job.name)
    status_path = job / "status.json"
    if not status_path.is_file():
        continue
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"malformed retained status: {job.name}") from exc
    if status.get("status") in {"queued", "running"}:
        active.append(job.name)
if locks or active:
    raise SystemExit(f"job store is not quiescent: active={len(active)} locks={len(locks)}")
print("job-store-quiescent=pass")
PY

echo
echo "===== PRE-ROLLBACK INTEGRITY ====="
ENV_SHA_BEFORE="$(sha256sum "$ROOT_DIR/config/env" | awk '{print $1}')"
printf '%s\n' "$ENV_SHA_BEFORE" > "$EVIDENCE_DIR/env-before.sha256"
"$PYTHON" "$EVIDENCE_DIR/snapshot_job_integrity.py" \
    "$ROOT_DIR/books/jobs/$JOB_ID" \
    "$EVIDENCE_DIR/job-before.json"
snapshot_store "$EVIDENCE_DIR/store-before.json"
snapshot_logs "$EVIDENCE_DIR/logs-before.json"
git log -n 12 --decorate --oneline > "$EVIDENCE_DIR/git-before.txt"
git status --short --branch > "$EVIDENCE_DIR/git-status-before.txt"
echo "pre-rollback-integrity=pass"

echo
echo "===== RESET TRACKED APPLICATION CHECKOUT ====="
git reset --hard "$TARGET_COMMIT"
[[ "$(git rev-parse HEAD)" == "$TARGET_COMMIT" ]] || fail "working tree did not reach target commit"
"$PYTHON" "$ROOT_DIR/scripts/normalise_tracked_permissions.py" --root "$ROOT_DIR"
"$PYTHON" -m compileall -q app scripts
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "target checkout is not clean"
echo "tracked-checkout-target=pass"

echo
echo "===== PERSISTENT DATA AFTER RESET ====="
ENV_SHA_AFTER_RESET="$(sha256sum "$ROOT_DIR/config/env" | awk '{print $1}')"
[[ "$ENV_SHA_AFTER_RESET" == "$ENV_SHA_BEFORE" ]] || fail "config/env changed during rollback"
snapshot_store "$EVIDENCE_DIR/store-after-reset.json"
cmp -s "$EVIDENCE_DIR/store-before.json" "$EVIDENCE_DIR/store-after-reset.json" || fail "job store changed during tracked reset"
snapshot_logs "$EVIDENCE_DIR/logs-after-reset.json"
cmp -s "$EVIDENCE_DIR/logs-before.json" "$EVIDENCE_DIR/logs-after-reset.json" || fail "operational logs changed while services were stopped"
echo "persistent-reset-boundary=pass"

echo
echo "===== START SERVICES ====="
systemctl start "$API_SERVICE"
systemctl start "$WORKER_SERVICE"
SERVICES_STOPPED=0
systemctl is-active "$API_SERVICE"
systemctl is-active "$WORKER_SERVICE"

wait_url "local-health" "$LOCAL_BASE/health"
wait_url "local-readiness" "$LOCAL_BASE/ready"
wait_url "local-status" "$LOCAL_BASE/api/v1/status"
wait_url "public-health" "$PUBLIC_BASE/health" 1
wait_url "public-readiness" "$PUBLIC_BASE/ready" 1
wait_url "public-status" "$PUBLIC_BASE/api/v1/status" 1

curl -fsS "$LOCAL_BASE/health" > "$EVIDENCE_DIR/local-health.json"
curl -fsS "$LOCAL_BASE/ready" > "$EVIDENCE_DIR/local-ready.json"
curl -fsS "$LOCAL_BASE/api/v1/status" > "$EVIDENCE_DIR/local-status.json"
curl -fsS -4 "$PUBLIC_BASE/health" > "$EVIDENCE_DIR/public-health.json"
curl -fsS -4 "$PUBLIC_BASE/ready" > "$EVIDENCE_DIR/public-ready.json"
curl -fsS -4 "$PUBLIC_BASE/api/v1/status" > "$EVIDENCE_DIR/public-status.json"

echo
echo "===== POST-ROLLBACK JOB AND DOWNLOAD PROOF ====="
"$PYTHON" "$EVIDENCE_DIR/snapshot_job_integrity.py" \
    "$ROOT_DIR/books/jobs/$JOB_ID" \
    "$EVIDENCE_DIR/job-after.json"
cmp -s "$EVIDENCE_DIR/job-before.json" "$EVIDENCE_DIR/job-after.json" || fail "completed job changed across rollback"
"$PYTHON" "$EVIDENCE_DIR/verify_job_downloads.py" \
    --root "$ROOT_DIR" \
    --job-id "$JOB_ID" \
    --base-url "$LOCAL_BASE" \
    --env-file "$ROOT_DIR/config/env" \
    --output "$EVIDENCE_DIR/job-downloads.json"
ENV_SHA_FINAL="$(sha256sum "$ROOT_DIR/config/env" | awk '{print $1}')"
[[ "$ENV_SHA_FINAL" == "$ENV_SHA_BEFORE" ]] || fail "config/env changed after service recovery"
"$PYTHON" "$EVIDENCE_DIR/verify_operational_logs.py" \
    "$EVIDENCE_DIR/logs-before.json" \
    "$ROOT_DIR/logs" \
    --output "$EVIDENCE_DIR/logs-after-service-recovery.json"

git log -n 12 --decorate --oneline > "$EVIDENCE_DIR/git-after.txt"
git status --short --branch > "$EVIDENCE_DIR/git-status-after.txt"
systemctl show "$API_SERVICE" "$WORKER_SERVICE" \
    --property=Id,ActiveState,SubState,Result,ExecMainStatus,FragmentPath \
    > "$EVIDENCE_DIR/services-after.txt"

DURATION="$(( $(date +%s) - STARTED_AT ))"
cat > "$EVIDENCE_DIR/result.txt" <<EOF
rollback-result=PASS
previous-commit=$EXPECTED_CURRENT
restored-commit=$TARGET_COMMIT
job-id=$JOB_ID
duration-seconds=$DURATION
evidence=$EVIDENCE_DIR
EOF

echo
echo "===== H-09 ROLLBACK RESULT ====="
cat "$EVIDENCE_DIR/result.txt"
trap - EXIT
