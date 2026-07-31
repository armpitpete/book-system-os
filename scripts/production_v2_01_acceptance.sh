#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_REPO_ROOT="/opt/book-system"
RUNTIME_ROOT="/opt/book-system-runtime/pandoc"
LOG_ROOT="/var/log/book-system"
API_SERVICE="book-system-api.service"
WORKER_SERVICE="book-system-worker.service"
EXPECTED_COMMIT=""
REPO_ROOT="$DEFAULT_REPO_ROOT"
EXECUTE=0
WORK_DIR=""
CANDIDATE_TREE=""
CANDIDATE_PARENT_ROOT="/run"

usage() {
  cat <<'EOF'
Usage:
  sudo bash production_v2_01_acceptance.sh \
    --repo-root /opt/book-system \
    --expected-commit <accepted-40-char-commit> \
    --execute

This is the single reviewed production operation for the V2-01 gate. It:

1. verifies that this launcher and origin/main belong to the exact candidate;
2. installs the pinned, digest-verified Pandoc runtime;
3. proves sandbox compatibility as root and www-data;
4. runs the repository's exact guarded deployment;
5. proves health, readiness, authentication, valid and invalid validation;
6. builds temporary standard PDF, ND PDF, EPUB and DOCX outputs;
7. proves retained book storage is unchanged; and
8. writes one protected acceptance log.

Without --execute, no production mutation is authorised.
EOF
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$CANDIDATE_TREE" && -d "$CANDIDATE_TREE" ]]; then
    case "$(basename "$CANDIDATE_TREE")" in
      book-system-candidate-tree.*)
        rm -rf -- "$CANDIDATE_TREE"
        ;;
      *)
        echo "refusing-to-clean-unexpected-candidate-tree=$CANDIDATE_TREE" >&2
        ;;
    esac
  fi
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf -- "$WORK_DIR"
  fi
}

write_retained_jobs_manifest() {
  local destination="$1"
  python3 - "$REPO_ROOT" "$destination" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import stat
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2])
root = repo_root / "books" / "jobs"
allowed_tracked = {"books/jobs/.gitkeep"}
records: list[dict[str, object]] = []

tracked_result = subprocess.run(
    ["git", "-C", str(repo_root), "ls-files", "-z", "--", "books/jobs"],
    check=True,
    stdout=subprocess.PIPE,
)
tracked_paths = {
    item.decode("utf-8", errors="surrogateescape")
    for item in tracked_result.stdout.split(b"\0")
    if item
}
unexpected_tracked = sorted(tracked_paths - allowed_tracked)
if unexpected_tracked:
    raise SystemExit(
        "unexpected tracked path under books/jobs: "
        + ", ".join(unexpected_tracked[:20])
    )

if not root.exists() or not root.is_dir() or root.is_symlink():
    raise SystemExit("persistent jobs root is not a real directory")

records.append({"path": ".", "type": "directory"})
stack = [root]
while stack:
    current = stack.pop()
    entries = sorted(os.scandir(current), key=lambda entry: entry.name)
    directories: list[Path] = []
    for entry in entries:
        path = Path(entry.path)
        relative = path.relative_to(root).as_posix()
        if relative == ".gitkeep" and "books/jobs/.gitkeep" in tracked_paths:
            continue

        metadata = path.lstat()
        record: dict[str, object] = {
            "path": relative,
            "mode": stat.S_IMODE(metadata.st_mode),
        }
        if stat.S_ISDIR(metadata.st_mode):
            record["type"] = "directory"
            directories.append(path)
        elif stat.S_ISREG(metadata.st_mode):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            record.update(
                type="file",
                size=metadata.st_size,
                sha256=digest.hexdigest(),
            )
        elif stat.S_ISLNK(metadata.st_mode):
            record.update(type="symlink", target=os.readlink(path))
        else:
            record["type"] = "other"
        records.append(record)
    stack.extend(reversed(directories))

destination.write_text(
    json.dumps(records, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
PY
}

compare_retained_jobs_manifests() {
  local before="$1"
  local after="$2"
  python3 - "$before" "$after" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MAX_ITEMS = 25
SAFE_VALUE_PROPERTIES = {"type", "mode", "size", "target"}


def load(path: str) -> dict[str, dict[str, Any]]:
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    return {record["path"]: record for record in records}


def brief(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": record["path"],
        "type": record.get("type"),
    }
    if "mode" in record:
        result["mode"] = record["mode"]
    if "size" in record:
        result["size"] = record["size"]
    return result


before = load(sys.argv[1])
after = load(sys.argv[2])

added: list[dict[str, Any]] = []
removed: list[dict[str, Any]] = []
changed: list[dict[str, Any]] = []

for path in sorted(set(before) | set(after)):
    if path not in before:
        added.append(brief(after[path]))
        continue
    if path not in after:
        removed.append(brief(before[path]))
        continue
    before_record = before[path]
    after_record = after[path]
    properties = sorted(
        key
        for key in set(before_record) | set(after_record)
        if key != "path" and before_record.get(key) != after_record.get(key)
    )
    if not properties:
        continue
    item: dict[str, Any] = {
        "path": path,
        "properties": properties,
    }
    for property_name in properties:
        if property_name not in SAFE_VALUE_PROPERTIES:
            continue
        item[f"before_{property_name}"] = before_record.get(property_name)
        item[f"after_{property_name}"] = after_record.get(property_name)
    changed.append(item)

if not added and not removed and not changed:
    raise SystemExit(0)

summary = {
    "status": "mismatch",
    "added_count": len(added),
    "removed_count": len(removed),
    "changed_count": len(changed),
    "added": added[:MAX_ITEMS],
    "removed": removed[:MAX_ITEMS],
    "changed": changed[:MAX_ITEMS],
    "truncated": any(
        len(items) > MAX_ITEMS for items in (added, removed, changed)
    ),
}
print(
    "retained-jobs-mismatch="
    + json.dumps(summary, sort_keys=True, separators=(",", ":"))
)
raise SystemExit(1)
PY
}

stage_candidate_tree() {
  if [[ -z "$CANDIDATE_TREE" ]]; then
    CANDIDATE_TREE="$(mktemp -d -p "$CANDIDATE_PARENT_ROOT" book-system-candidate-tree.XXXXXXXXXX)"
  else
    install -d -m 0700 "$CANDIDATE_TREE"
  fi
  git archive "$EXPECTED_COMMIT" | tar -x -C "$CANDIDATE_TREE"
  for required in \
    scripts/install_pinned_pandoc.sh \
    scripts/check_runtime_compatibility.py \
    scripts/deploy_server.sh \
    scripts/v2_01_live_acceptance.py; do
    [[ -f "$CANDIDATE_TREE/$required" ]] \
      || fail "candidate execution surface is missing $required"
  done
  echo "candidate-execution-surface=$CANDIDATE_TREE"
  echo "candidate-execution-commit=$EXPECTED_COMMIT"
}

make_candidate_execution_surface_service_readable() {
  [[ -n "$CANDIDATE_TREE" && -d "$CANDIDATE_TREE" ]] \
    || fail "candidate execution surface has not been staged"
  chown -hR root:www-data "$CANDIDATE_TREE"
  find "$CANDIDATE_TREE" -type d -exec chmod 0750 {} +
  find "$CANDIDATE_TREE" -type f -exec chmod 0640 {} +
  find "$CANDIDATE_TREE" -type f -perm /111 -exec chmod 0750 {} +
  echo "candidate-execution-surface-owner=root:www-data"
  echo "candidate-execution-surface-mode=service-readable-nonwritable"
}

verify_candidate_execution_surface_service_boundary() {
  local compatibility_script
  local parent_path
  local writable_path

  compatibility_script="$(candidate_file scripts/check_runtime_compatibility.py)"

  runuser -u www-data -- test -x "$CANDIDATE_TREE" \
    || fail "www-data cannot traverse the staged candidate execution surface"
  runuser -u www-data -- test -r "$compatibility_script" \
    || fail "www-data cannot read the staged candidate compatibility script"
  runuser -u www-data -- test -r "$CANDIDATE_TREE/app/services/pandoc_capability.py" \
    || fail "www-data cannot read staged candidate application code"

  if ! writable_path="$(runuser -u www-data -- find "$CANDIDATE_TREE" -writable -print -quit)"; then
    fail "www-data cannot inspect staged candidate writability"
  fi
  [[ -z "$writable_path" ]] \
    || fail "www-data can write the staged candidate execution surface: $writable_path"

  parent_path="$CANDIDATE_TREE"
  while true; do
    runuser -u www-data -- test ! -w "$parent_path" \
      || fail "www-data can write candidate parent path: $parent_path"
    [[ "$parent_path" == "/" ]] && break
    parent_path="$(dirname "$parent_path")"
  done

  echo "candidate-execution-surface-www-data-readability=pass"
  echo "candidate-execution-surface-www-data-nonwritable=pass"
}

candidate_file() {
  local relative_path="$1"
  local path="$CANDIDATE_TREE/$relative_path"
  [[ -f "$path" ]] || fail "candidate execution file is missing: $relative_path"
  printf '%s\n' "$path"
}

install_candidate_pandoc_runtime() {
  local installer
  installer="$(candidate_file scripts/install_pinned_pandoc.sh)"
  bash "$installer" --runtime-root "$RUNTIME_ROOT"
}

run_candidate_runtime_capability() {
  local compatibility_script
  compatibility_script="$(candidate_file scripts/check_runtime_compatibility.py)"
  echo "candidate-runtime-compatibility-script=$compatibility_script"
  "$REPO_ROOT/.venv/bin/python" "$compatibility_script" --pandoc-only
  runuser -u www-data -- env PATH="$PATH" \
    "$REPO_ROOT/.venv/bin/python" "$compatibility_script" --pandoc-only
}

run_candidate_guarded_deployment() {
  local deploy_script
  deploy_script="$(candidate_file scripts/deploy_server.sh)"
  echo "candidate-deployment-script=$deploy_script"
  echo "candidate-deployment-target=$REPO_ROOT"
  env PATH="$PATH" \
    bash "$deploy_script" \
      --repo-root "$REPO_ROOT" \
      --expected-commit "$EXPECTED_COMMIT"
}

main() {
  trap cleanup EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  while (($#)); do
    case "$1" in
      --repo-root)
        REPO_ROOT="${2:-}"
        shift 2
        ;;
      --expected-commit)
        EXPECTED_COMMIT="${2:-}"
        shift 2
        ;;
      --execute)
        EXECUTE=1
        shift
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

  [[ "$EXECUTE" -eq 1 ]] || {
    usage >&2
    fail "production mutation requires the explicit --execute flag"
  }
  [[ "$(id -u)" -eq 0 ]] || fail "run as root"
  [[ "$REPO_ROOT" == /* && "$REPO_ROOT" != "/" ]] || fail "repo root must be a bounded absolute path"
  [[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit must be a full lowercase SHA-1"

  for command_name in git sha256sum flock systemctl runuser python3 tar install mktemp chown chmod find; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
  done
  id -u www-data >/dev/null 2>&1 || fail "missing service account: www-data"

  [[ -d "$REPO_ROOT/.git" ]] || fail "repository is unavailable at $REPO_ROOT"
  cd "$REPO_ROOT"

  git fetch --prune origin
  [[ "$(git symbolic-ref --quiet --short HEAD)" == "main" ]] || fail "production checkout is not on main"
  [[ "$(git rev-parse origin/main)" == "$EXPECTED_COMMIT" ]] || fail "origin/main is not the exact accepted commit"
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "production checkout is not clean"
  git cat-file -e "$EXPECTED_COMMIT^{commit}" || fail "expected commit is unavailable"

  RUNNING_LAUNCHER_SHA="$(sha256sum "$0" | awk '{print $1}')"
  EXPECTED_LAUNCHER_SHA="$(git show "$EXPECTED_COMMIT:scripts/production_v2_01_acceptance.sh" | sha256sum | awk '{print $1}')"
  [[ "$RUNNING_LAUNCHER_SHA" == "$EXPECTED_LAUNCHER_SHA" ]] \
    || fail "running launcher is not the launcher stored in the exact accepted commit"

  CONFIG_FILE="$REPO_ROOT/config/env"
  [[ -f "$CONFIG_FILE" ]] || fail "missing protected production configuration"
  [[ "$(stat -c '%a' "$CONFIG_FILE")" == "600" ]] || fail "config/env mode is not 600"
  [[ "$(stat -c '%U:%G' "$CONFIG_FILE")" == "root:root" ]] || fail "config/env owner changed"

  install -d -m 0750 -o root -g root "$LOG_ROOT"
  WORK_DIR="$(mktemp -d)"
  chmod 0700 "$WORK_DIR"
  LOG_FILE="$LOG_ROOT/v2-01-acceptance-$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_COMMIT:0:12}.log"
  install -m 0600 -o root -g root /dev/null "$LOG_FILE"
  exec > >(tee -a "$LOG_FILE") 2>&1

  exec 9>"/run/lock/book-system-v2-01-acceptance.lock"
  flock -n 9 || fail "another V2-01 production operation is already running"

  echo "===== V2-01 PRODUCTION ACCEPTANCE ====="
  echo "started-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "repo-root=$REPO_ROOT"
  echo "expected-commit=$EXPECTED_COMMIT"
  echo "launcher-sha256=$RUNNING_LAUNCHER_SHA"
  echo "acceptance-log=$LOG_FILE"

  BEFORE_MANIFEST="$WORK_DIR/retained-jobs-before.json"
  AFTER_MANIFEST="$WORK_DIR/retained-jobs-after.json"
  write_retained_jobs_manifest "$BEFORE_MANIFEST"
  chmod 0600 "$BEFORE_MANIFEST"
  echo "retained-jobs-before-sha256=$(sha256sum "$BEFORE_MANIFEST" | awk '{print $1}')"

  echo
  echo "===== CANDIDATE EXECUTION SURFACE ====="
  stage_candidate_tree
  make_candidate_execution_surface_service_readable
  verify_candidate_execution_surface_service_boundary

  echo
  echo "===== PINNED PANDOC INSTALLATION ====="
  install_candidate_pandoc_runtime

  PANDOC_BIN="$RUNTIME_ROOT/current/bin/pandoc"
  [[ -x "$PANDOC_BIN" ]] || fail "pinned Pandoc binary was not activated"
  export PATH="$RUNTIME_ROOT/current/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  [[ "$(command -v pandoc)" == "$PANDOC_BIN" ]] || fail "shell did not resolve the pinned Pandoc binary"

  echo
  echo "===== ROOT AND SERVICE-ACCOUNT CAPABILITY ====="
  run_candidate_runtime_capability
  echo "root-and-www-data-pandoc-capability=pass"

  echo
  echo "===== EXACT GUARDED DEPLOYMENT ====="
  run_candidate_guarded_deployment

  EXPECTED_SERVICE_PATH="PATH=$PATH"
  for service in "$API_SERVICE" "$WORKER_SERVICE"; do
    INSTALLED_ENVIRONMENT="$(systemctl show "$service" --property=Environment --value)"
    [[ "$INSTALLED_ENVIRONMENT" == *"$EXPECTED_SERVICE_PATH"* ]] \
      || fail "$service does not contain the pinned runtime PATH"
  done
  echo "service-runtime-path=pass"

  echo
  echo "===== LIVE VALIDATION AND FOUR-FORMAT ACCEPTANCE ====="
  env PATH="$PATH" \
    "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/v2_01_live_acceptance.py" \
      --base-url "https://publish.toiletrage.co.uk" \
      --repo-root "$REPO_ROOT" \
      --env-file "$CONFIG_FILE" \
      --expected-commit "$EXPECTED_COMMIT"

  write_retained_jobs_manifest "$AFTER_MANIFEST"
  chmod 0600 "$AFTER_MANIFEST"
  compare_retained_jobs_manifests "$BEFORE_MANIFEST" "$AFTER_MANIFEST" \
    || fail "deployment or acceptance changed retained job data"
  echo "retained-jobs-after-sha256=$(sha256sum "$AFTER_MANIFEST" | awk '{print $1}')"
  echo "retained-jobs-unchanged=pass"
  echo "retained-books-unchanged=pass"

  [[ "$(git rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] || fail "final deployed commit changed"
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "final production checkout is not clean"
  systemctl is-active --quiet "$API_SERVICE" || fail "API service is not active at final acceptance"
  systemctl is-active --quiet "$WORKER_SERVICE" || fail "worker service is not active at final acceptance"

  echo
  echo "===== V2-01 ACCEPTANCE PASS ====="
  echo "completed-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "deployed-commit=$EXPECTED_COMMIT"
  echo "pandoc-path=$(readlink -f "$PANDOC_BIN")"
  echo "acceptance-log=$LOG_FILE"
  echo "v2-01-production-acceptance=pass"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
