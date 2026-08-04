#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
CANDIDATE_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd -P)"
REPO_ROOT="/opt/book-system"
EXPECTED_BEFORE=""
TARGET_COMMIT=""
PUBLIC_BASE_URL="https://publish.toiletrage.co.uk"
LOCAL_BASE_URL="http://127.0.0.1:8088"
ENV_FILE="/opt/book-system/config/env"
EVIDENCE_ROOT=""
CONFIRMATION=""

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/production_corpus_runtime_release.sh \
    --repo-root /opt/book-system \
    --expected-before <40-character-production-sha> \
    --target-commit <40-character-release-sha> \
    --confirm "DEPLOY <40-character-release-sha>" \
    [--env-file /opt/book-system/config/env] \
    [--public-base-url https://publish.toiletrage.co.uk] \
    [--local-base-url http://127.0.0.1:8088] \
    [--evidence-root /var/log/book-system/<new-directory>]

Run this file from a clean detached worktree at the exact target commit.
It reuses production_v2_01_acceptance.sh for the guarded deployment and
baseline acceptance, then runs the corpus-specific live acceptance program.
EOF
}

while (($#)); do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --expected-before)
      EXPECTED_BEFORE="$2"
      shift 2
      ;;
    --target-commit)
      TARGET_COMMIT="$2"
      shift 2
      ;;
    --confirm)
      CONFIRMATION="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --public-base-url)
      PUBLIC_BASE_URL="$2"
      shift 2
      ;;
    --local-base-url)
      LOCAL_BASE_URL="$2"
      shift 2
      ;;
    --evidence-root)
      EVIDENCE_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
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

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command is unavailable: $1"
}

git_value() {
  local root="$1"
  shift
  git -C "$root" "$@"
}

snapshot_tree() {
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
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            entries.append({
                "path": relative,
                "type": "symlink",
                "mode": mode,
                "target": os.readlink(path),
            })
        elif path.is_dir():
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            entries.append({
                "path": relative,
                "type": "file",
                "mode": mode,
                "bytes": metadata.st_size,
                "sha256": digest.hexdigest(),
            })
        else:
            entries.append({"path": relative, "type": "other", "mode": mode})

destination.write_text(
    json.dumps(entries, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.chmod(destination, 0o600)
PY
}

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "This protected release launcher must run as root." >&2
  exit 1
fi

is_sha "$EXPECTED_BEFORE" || {
  echo "--expected-before must be a full lowercase 40-character SHA." >&2
  exit 2
}
is_sha "$TARGET_COMMIT" || {
  echo "--target-commit must be a full lowercase 40-character SHA." >&2
  exit 2
}
[[ "$EXPECTED_BEFORE" != "$TARGET_COMMIT" ]] || {
  echo "The expected-before and target commits must differ." >&2
  exit 2
}
[[ "$CONFIRMATION" == "DEPLOY $TARGET_COMMIT" ]] || {
  echo "Typed confirmation must be exactly: DEPLOY $TARGET_COMMIT" >&2
  exit 2
}

for command in git sha256sum cmp systemctl tee /usr/bin/python3 bash; do
  require_command "$command"
done

REPO_ROOT="$(readlink -f "$REPO_ROOT")"
ENV_FILE="$(readlink -f "$ENV_FILE")"
[[ -d "$REPO_ROOT/.git" ]] || fail "Production repository is unavailable: $REPO_ROOT"
[[ -f "$ENV_FILE" ]] || fail "Protected environment file is unavailable: $ENV_FILE"
[[ -d "$CANDIDATE_ROOT/.git" || -f "$CANDIDATE_ROOT/.git" ]] || \
  fail "Launcher is not inside a Git worktree: $CANDIDATE_ROOT"

candidate_head="$(git_value "$CANDIDATE_ROOT" rev-parse HEAD)"
[[ "$candidate_head" == "$TARGET_COMMIT" ]] || \
  fail "Candidate worktree is at $candidate_head, not $TARGET_COMMIT"
[[ -z "$(git_value "$CANDIDATE_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || \
  fail "Candidate worktree is not clean"

candidate_script_hash="$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')"
committed_script_hash="$(git_value "$CANDIDATE_ROOT" show "$TARGET_COMMIT:scripts/production_corpus_runtime_release.sh" | sha256sum | awk '{print $1}')"
[[ "$candidate_script_hash" == "$committed_script_hash" ]] || \
  fail "Running launcher does not match the exact target commit"

production_branch="$(git_value "$REPO_ROOT" symbolic-ref --short HEAD)"
[[ "$production_branch" == "main" ]] || fail "Production repository is not on main"
production_head="$(git_value "$REPO_ROOT" rev-parse HEAD)"
[[ "$production_head" == "$EXPECTED_BEFORE" ]] || \
  fail "Production is at $production_head, not expected $EXPECTED_BEFORE"
[[ -z "$(git_value "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || \
  fail "Production repository is not clean"

git_value "$REPO_ROOT" fetch --prune origin
after_fetch_head="$(git_value "$REPO_ROOT" rev-parse HEAD)"
[[ "$after_fetch_head" == "$EXPECTED_BEFORE" ]] || \
  fail "Production HEAD changed during fetch"
origin_main="$(git_value "$REPO_ROOT" rev-parse origin/main)"
[[ "$origin_main" == "$TARGET_COMMIT" ]] || \
  fail "origin/main is $origin_main, not exact target $TARGET_COMMIT"
git_value "$REPO_ROOT" merge-base --is-ancestor "$EXPECTED_BEFORE" "$TARGET_COMMIT" || \
  fail "Target is not a descendant of the accepted production commit"

if [[ -z "$EVIDENCE_ROOT" ]]; then
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  EVIDENCE_ROOT="/var/log/book-system/corpus-runtime-${timestamp}-${TARGET_COMMIT:0:12}"
fi
[[ "$EVIDENCE_ROOT" = /* ]] || fail "--evidence-root must be an absolute path"
[[ ! -e "$EVIDENCE_ROOT" ]] || fail "Evidence path already exists: $EVIDENCE_ROOT"
mkdir -p "$EVIDENCE_ROOT"
chmod 0700 "$EVIDENCE_ROOT"

printf '%s\n' "$EXPECTED_BEFORE" >"$EVIDENCE_ROOT/expected-before.txt"
printf '%s\n' "$TARGET_COMMIT" >"$EVIDENCE_ROOT/target-commit.txt"
printf '%s\n' "$candidate_script_hash" >"$EVIDENCE_ROOT/launcher-sha256.txt"
chmod 0600 "$EVIDENCE_ROOT"/*.txt

snapshot_tree "$REPO_ROOT/books/jobs" "$EVIDENCE_ROOT/storage-before.json"
snapshot_tree "$REPO_ROOT/config" "$EVIDENCE_ROOT/config-before.json"
snapshot_tree "/etc/systemd/system" "$EVIDENCE_ROOT/systemd-before.json"

set +e
bash "$CANDIDATE_ROOT/scripts/production_v2_01_acceptance.sh" \
  --repo-root "$REPO_ROOT" \
  --expected-commit "$TARGET_COMMIT" \
  --execute \
  2>&1 | tee "$EVIDENCE_ROOT/deployment-and-baseline.log"
deployment_status=${PIPESTATUS[0]}
set -e
chmod 0600 "$EVIDENCE_ROOT/deployment-and-baseline.log"
[[ "$deployment_status" -eq 0 ]] || \
  fail "Guarded deployment or baseline V2-01 acceptance failed"

[[ "$(git_value "$REPO_ROOT" rev-parse HEAD)" == "$TARGET_COMMIT" ]] || \
  fail "Production did not finish at the exact target commit"
[[ -z "$(git_value "$REPO_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || \
  fail "Production repository is not clean after deployment"

python_bin="$REPO_ROOT/.venv/bin/python"
[[ -x "$python_bin" ]] || fail "Production virtualenv Python is unavailable"

set +e
"$python_bin" "$REPO_ROOT/scripts/corpus_runtime_live_acceptance.py" \
  --public-base-url "$PUBLIC_BASE_URL" \
  --local-base-url "$LOCAL_BASE_URL" \
  --repo-root "$REPO_ROOT" \
  --env-file "$ENV_FILE" \
  --expected-commit "$TARGET_COMMIT" \
  --evidence-dir "$EVIDENCE_ROOT/corpus-live-acceptance" \
  2>&1 | tee "$EVIDENCE_ROOT/corpus-live-acceptance.log"
acceptance_status=${PIPESTATUS[0]}
set -e
chmod 0600 "$EVIDENCE_ROOT/corpus-live-acceptance.log"
[[ "$acceptance_status" -eq 0 ]] || fail "Corpus-specific live acceptance failed"

snapshot_tree "$REPO_ROOT/books/jobs" "$EVIDENCE_ROOT/storage-after.json"
snapshot_tree "$REPO_ROOT/config" "$EVIDENCE_ROOT/config-after.json"
snapshot_tree "/etc/systemd/system" "$EVIDENCE_ROOT/systemd-after.json"

cmp -s "$EVIDENCE_ROOT/storage-before.json" "$EVIDENCE_ROOT/storage-after.json" || \
  fail "Persistent job storage changed during deployment or acceptance"
cmp -s "$EVIDENCE_ROOT/config-before.json" "$EVIDENCE_ROOT/config-after.json" || \
  fail "Protected repository configuration changed during deployment"
cmp -s "$EVIDENCE_ROOT/systemd-before.json" "$EVIDENCE_ROOT/systemd-after.json" || \
  fail "Installed systemd unit content or metadata changed unexpectedly"

for unit in book-system-api.service book-system-worker.service; do
  systemctl is-active --quiet "$unit" || fail "$unit is not active after acceptance"
done

cat >"$EVIDENCE_ROOT/result.txt" <<EOF
PASS
expected_before=$EXPECTED_BEFORE
target_commit=$TARGET_COMMIT
production_head=$(git_value "$REPO_ROOT" rev-parse HEAD)
persistent_storage_unchanged=true
protected_config_unchanged=true
systemd_units_unchanged=true
baseline_acceptance=pass
corpus_live_acceptance=pass
EOF
chmod 0600 "$EVIDENCE_ROOT/result.txt"

printf '\nCORPUS RUNTIME RELEASE — PASS\n'
printf 'Expected before: %s\n' "$EXPECTED_BEFORE"
printf 'Deployed commit: %s\n' "$TARGET_COMMIT"
printf 'Evidence: %s\n' "$EVIDENCE_ROOT"
