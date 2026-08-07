#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
CANDIDATE_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd -P)"
BASE_LAUNCHER="$CANDIDATE_ROOT/scripts/production_corpus_runtime_release_configured.sh"
BACKUP_LAUNCHER="$CANDIDATE_ROOT/scripts/backup_persistent_state.sh"
LIVE_ACCEPTANCE="$CANDIDATE_ROOT/scripts/current_main_live_acceptance.py"
REPO_ROOT="/opt/book-system"
EXPECTED_BEFORE=""
TARGET_COMMIT=""
PUBLIC_BASE_URL="https://publish.toiletrage.co.uk"
ENV_FILE="/opt/book-system/config/env"
EVIDENCE_ROOT=""
CONFIRMATION=""

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/production_current_main_release.sh \
    --repo-root /opt/book-system \
    --expected-before <40-character-production-sha> \
    --target-commit <40-character-release-sha> \
    --confirm "DEPLOY <40-character-release-sha>" \
    [--env-file /opt/book-system/config/env] \
    [--public-base-url https://publish.toiletrage.co.uk] \
    [--evidence-root /var/log/book-system/<new-directory>]

Run from a clean detached worktree at the exact target commit.
This wrapper adds Revision Studio persistent-state backup/invariants and the
current-delta live acceptance around the established protected corpus release.
EOF
}

while (($#)); do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --expected-before) EXPECTED_BEFORE="$2"; shift 2 ;;
    --target-commit) TARGET_COMMIT="$2"; shift 2 ;;
    --confirm) CONFIRMATION="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --public-base-url) PUBLIC_BASE_URL="$2"; shift 2 ;;
    --evidence-root) EVIDENCE_ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

fail() {
  local message="$1"
  echo "ERROR: $message" >&2
  if [[ -n "${EVIDENCE_ROOT:-}" && -d "$EVIDENCE_ROOT" ]]; then
    printf 'FAIL\n%s\n' "$message" >"$EVIDENCE_ROOT/result.txt"
    chmod 0600 "$EVIDENCE_ROOT/result.txt"
  fi
  exit 1
}

is_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

snapshot_revisions() {
  local root="$1"
  local destination="$2"
  /usr/bin/python3 - "$root" "$destination" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
entries = []
if root.exists():
    if root.is_symlink() or not root.is_dir():
        raise SystemExit("Revision Studio root is not a safe directory")
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        for name in sorted(directories):
            path = current / name
            if path.is_symlink():
                raise SystemExit(f"Revision Studio symlink is not allowed: {path}")
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "type": "directory",
                "mode": stat.S_IMODE(path.stat().st_mode),
            })
        for name in sorted(files):
            if name == ".gitkeep":
                continue
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise SystemExit(f"Unsafe Revision Studio entry: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append({
                "path": path.relative_to(root).as_posix(),
                "type": "file",
                "mode": stat.S_IMODE(path.stat().st_mode),
                "bytes": path.stat().st_size,
                "sha256": digest,
            })
destination.write_text(
    json.dumps(sorted(entries, key=lambda item: (item["path"], item["type"])), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.chmod(destination, 0o600)
PY
}

[[ "${EUID:-$(id -u)}" -eq 0 ]] || {
  echo "This protected release wrapper must run as root." >&2
  exit 1
}
is_sha "$EXPECTED_BEFORE" || { echo "--expected-before must be a full lowercase SHA" >&2; exit 2; }
is_sha "$TARGET_COMMIT" || { echo "--target-commit must be a full lowercase SHA" >&2; exit 2; }
[[ "$EXPECTED_BEFORE" != "$TARGET_COMMIT" ]] || { echo "expected-before and target must differ" >&2; exit 2; }
[[ "$CONFIRMATION" == "DEPLOY $TARGET_COMMIT" ]] || {
  echo "Typed confirmation must be exactly: DEPLOY $TARGET_COMMIT" >&2
  exit 2
}

for path in "$BASE_LAUNCHER" "$BACKUP_LAUNCHER" "$LIVE_ACCEPTANCE"; do
  [[ -f "$path" ]] || fail "Required reviewed release component is unavailable: $path"
done
[[ -d "$CANDIDATE_ROOT/.git" || -f "$CANDIDATE_ROOT/.git" ]] || fail "Candidate is not a Git worktree"
[[ "$(git -C "$CANDIDATE_ROOT" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || fail "Candidate is not at exact target"
[[ -z "$(git -C "$CANDIDATE_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "Candidate worktree is not clean"

running_hash="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"
committed_hash="$(git -C "$CANDIDATE_ROOT" show "$TARGET_COMMIT:scripts/production_current_main_release.sh" | sha256sum | awk '{print $1}')"
[[ "$running_hash" == "$committed_hash" ]] || fail "Running wrapper does not match exact target commit"

REPO_ROOT="$(readlink -f "$REPO_ROOT")"
ENV_FILE="$(readlink -f "$ENV_FILE")"
[[ -d "$REPO_ROOT/.git" ]] || fail "Production repository is unavailable: $REPO_ROOT"
[[ -f "$ENV_FILE" ]] || fail "Protected environment file is unavailable: $ENV_FILE"
[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$EXPECTED_BEFORE" ]] || fail "Production is not at exact expected-before commit"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "Production repository is not clean before release"

git -C "$REPO_ROOT" fetch --prune origin
[[ "$(git -C "$REPO_ROOT" rev-parse origin/main)" == "$TARGET_COMMIT" ]] || fail "origin/main is not the exact target"
git -C "$REPO_ROOT" merge-base --is-ancestor "$EXPECTED_BEFORE" "$TARGET_COMMIT" || fail "Target is not a descendant of production"

if [[ -z "$EVIDENCE_ROOT" ]]; then
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  EVIDENCE_ROOT="/var/log/book-system/current-main-${timestamp}-${TARGET_COMMIT:0:12}"
fi
[[ "$EVIDENCE_ROOT" = /* ]] || fail "--evidence-root must be absolute"
[[ ! -e "$EVIDENCE_ROOT" ]] || fail "Evidence path already exists: $EVIDENCE_ROOT"
mkdir -p "$EVIDENCE_ROOT"
chmod 0700 "$EVIDENCE_ROOT"

printf '%s\n' "$EXPECTED_BEFORE" >"$EVIDENCE_ROOT/expected-before.txt"
printf '%s\n' "$TARGET_COMMIT" >"$EVIDENCE_ROOT/target-commit.txt"
printf '%s\n' "$running_hash" >"$EVIDENCE_ROOT/wrapper-sha256.txt"
chmod 0600 "$EVIDENCE_ROOT"/*.txt

snapshot_revisions "$REPO_ROOT/books/revisions" "$EVIDENCE_ROOT/revisions-before.json"

set +e
bash "$BACKUP_LAUNCHER" \
  --root "$REPO_ROOT" \
  "$EVIDENCE_ROOT/predeploy-persistent-state.tar.gz" \
  2>&1 | tee "$EVIDENCE_ROOT/predeploy-backup.log"
backup_status=${PIPESTATUS[0]}
set -e
chmod 0600 "$EVIDENCE_ROOT/predeploy-backup.log"
[[ "$backup_status" -eq 0 ]] || fail "Pre-deploy persistent-state backup failed"

set +e
bash "$BASE_LAUNCHER" \
  --repo-root "$REPO_ROOT" \
  --expected-before "$EXPECTED_BEFORE" \
  --target-commit "$TARGET_COMMIT" \
  --confirm "$CONFIRMATION" \
  --env-file "$ENV_FILE" \
  --public-base-url "$PUBLIC_BASE_URL" \
  --evidence-root "$EVIDENCE_ROOT/base-release" \
  2>&1 | tee "$EVIDENCE_ROOT/base-release.log"
base_status=${PIPESTATUS[0]}
set -e
chmod 0600 "$EVIDENCE_ROOT/base-release.log"
[[ "$base_status" -eq 0 ]] || fail "Established protected corpus release failed"

[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || fail "Production did not finish at exact target"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "Production repository is not clean after base release"

python_bin="$REPO_ROOT/.venv/bin/python"
[[ -x "$python_bin" ]] || fail "Production virtualenv Python is unavailable"
set +e
(
  cd "$REPO_ROOT"
  "$python_bin" "$REPO_ROOT/scripts/current_main_live_acceptance.py" \
    --repo-root "$REPO_ROOT" \
    --env-file "$ENV_FILE" \
    --expected-commit "$TARGET_COMMIT" \
    --public-base-url "$PUBLIC_BASE_URL" \
    --evidence-dir "$EVIDENCE_ROOT/current-main-live"
) 2>&1 | tee "$EVIDENCE_ROOT/current-main-live.log"
live_status=${PIPESTATUS[0]}
set -e
chmod 0600 "$EVIDENCE_ROOT/current-main-live.log"
[[ "$live_status" -eq 0 ]] || fail "Current-main live acceptance failed"

snapshot_revisions "$REPO_ROOT/books/revisions" "$EVIDENCE_ROOT/revisions-after.json"
cmp -s "$EVIDENCE_ROOT/revisions-before.json" "$EVIDENCE_ROOT/revisions-after.json" || fail "Revision Studio persistent state changed during release acceptance"

[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || fail "Final production commit changed"
[[ -z "$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "Release left production repository changes"
for unit in book-system-api.service book-system-worker.service; do
  systemctl is-active --quiet "$unit" || fail "$unit is not active after current-main acceptance"
done

cat >"$EVIDENCE_ROOT/result.txt" <<EOF
PASS
expected_before=$EXPECTED_BEFORE
target_commit=$TARGET_COMMIT
production_head=$(git -C "$REPO_ROOT" rev-parse HEAD)
predeploy_persistent_backup=pass
base_corpus_release=pass
current_main_live_acceptance=pass
revision_persistent_state_unchanged=true
actual_book_readiness_claimed=false
EOF
chmod 0600 "$EVIDENCE_ROOT/result.txt"

printf '\nCURRENT MAIN RELEASE — PASS\n'
printf 'Expected before: %s\n' "$EXPECTED_BEFORE"
printf 'Deployed commit: %s\n' "$TARGET_COMMIT"
printf 'Revision persistent state unchanged: true\n'
printf 'Actual book readiness claimed: false\n'
printf 'Evidence: %s\n' "$EVIDENCE_ROOT"
