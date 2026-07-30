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
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf -- "$WORK_DIR"
  fi
}

write_books_manifest() {
  local destination="$1"
  python3 - "$REPO_ROOT/books" "$destination" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
destination = Path(sys.argv[2])
records: list[dict[str, object]] = []

if root.exists():
    if not root.is_dir() or root.is_symlink():
        raise SystemExit("persistent books root is not a real directory")
    stack = [root]
    while stack:
        current = stack.pop()
        paths = [current] if current == root else []
        if current == root:
            paths = [root]
        entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        paths.extend(Path(entry.path) for entry in entries)
        directories: list[Path] = []
        for path in paths:
            metadata = path.lstat()
            relative = "." if path == root else path.relative_to(root).as_posix()
            record: dict[str, object] = {
                "path": relative,
                "mode": stat.S_IMODE(metadata.st_mode),
            }
            if stat.S_ISDIR(metadata.st_mode):
                record["type"] = "directory"
                if path != root:
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

stage_candidate_tree() {
  CANDIDATE_TREE="$WORK_DIR/candidate-tree"
  install -d -m 0700 "$CANDIDATE_TREE"
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

  for command_name in git sha256sum flock systemctl runuser python3 tar install; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
  done

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

  BEFORE_MANIFEST="$WORK_DIR/books-before.json"
  AFTER_MANIFEST="$WORK_DIR/books-after.json"
  write_books_manifest "$BEFORE_MANIFEST"
  echo "retained-books-before-sha256=$(sha256sum "$BEFORE_MANIFEST" | awk '{print $1}')"

  echo
  echo "===== CANDIDATE EXECUTION SURFACE ====="
  stage_candidate_tree

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

  write_books_manifest "$AFTER_MANIFEST"
  cmp --silent "$BEFORE_MANIFEST" "$AFTER_MANIFEST" \
    || fail "deployment or acceptance changed retained book storage"
  echo "retained-books-after-sha256=$(sha256sum "$AFTER_MANIFEST" | awk '{print $1}')"
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
