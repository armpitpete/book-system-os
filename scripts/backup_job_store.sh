#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/backup_job_store.sh [--root PATH] ARCHIVE.tar.gz

Create a validated Book System OS job-store backup without mutating the source.
The job store must be quiescent: no queued/running jobs and no job lock files.
EOF
}

ROOT="${BOOK_SYSTEM_ROOT:-}"

if [ "${1:-}" = "--root" ]; then
  [ "$#" -ge 3 ] || {
    usage >&2
    exit 2
  }
  ROOT="$2"
  shift 2
fi

[ "$#" -eq 1 ] || {
  usage >&2
  exit 2
}

ARCHIVE="$1"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ -z "$ROOT" ]; then
  ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
fi

ROOT="$(CDPATH= cd -- "$ROOT" && pwd)"
[ -d "$ROOT/books/jobs" ] || {
  echo "backup=fail: missing job store: $ROOT/books/jobs" >&2
  exit 1
}

ARCHIVE_DIR="$(dirname -- "$ARCHIVE")"
ARCHIVE_NAME="$(basename -- "$ARCHIVE")"
mkdir -p -- "$ARCHIVE_DIR"
ARCHIVE_DIR="$(CDPATH= cd -- "$ARCHIVE_DIR" && pwd)"
ARCHIVE="$ARCHIVE_DIR/$ARCHIVE_NAME"

[ ! -e "$ARCHIVE" ] || {
  echo "backup=fail: destination already exists: $ARCHIVE" >&2
  exit 1
}

TMP_DIR="$(mktemp -d "$ARCHIVE_DIR/.book-system-backup.XXXXXX")"
PARTIAL="$ARCHIVE_DIR/.$ARCHIVE_NAME.partial.$$"
cleanup() {
  rm -rf -- "$TMP_DIR"
  rm -f -- "$PARTIAL"
}
trap cleanup EXIT HUP INT TERM

STAGING="$TMP_DIR/book-system-backup"

python3 - "$ROOT" "$STAGING" <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
staging = Path(sys.argv[2]).resolve()
jobs_source = root / "books" / "jobs"
logs_source = root / "logs"
env_path = root / "config" / "env"
env_example = root / "config" / "env.example"

if not jobs_source.is_dir():
    raise SystemExit(f"backup=fail: missing job store: {jobs_source}")


def load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"backup=fail: invalid required JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"backup=fail: required JSON is not an object: {path}")
    return value


active: list[str] = []
for job_dir in sorted(path for path in jobs_source.iterdir() if path.is_dir()):
    status_path = job_dir / "status.json"
    if not status_path.is_file():
        raise SystemExit(f"backup=fail: job has no status.json: {job_dir.name}")
    status = load_json_object(status_path)
    if status.get("status") in {"queued", "running"}:
        active.append(f"{job_dir.name}:{status.get('status')}")
    if (job_dir / ".lock").exists():
        active.append(f"{job_dir.name}:lock")

if active:
    raise SystemExit(
        "backup=fail: job store is not quiescent; stop submissions and wait for jobs: "
        + ", ".join(active)
    )


def reject_symlinks(source: Path) -> None:
    if not source.exists():
        return
    for current_root, directories, files in os.walk(source, followlinks=False):
        current = Path(current_root)
        for name in [*directories, *files]:
            candidate = current / name
            if candidate.is_symlink():
                raise SystemExit(f"backup=fail: symbolic links are not allowed: {candidate}")


reject_symlinks(jobs_source)
reject_symlinks(logs_source)

(staging / "books" / "jobs").mkdir(parents=True)
(staging / "logs").mkdir(parents=True)
(staging / "config").mkdir(parents=True)


def ignore_ephemeral(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == ".lock"}


shutil.copytree(
    jobs_source,
    staging / "books" / "jobs",
    dirs_exist_ok=True,
    copy_function=shutil.copy2,
    ignore=ignore_ephemeral,
)
if logs_source.is_dir():
    shutil.copytree(
        logs_source,
        staging / "logs",
        dirs_exist_ok=True,
        copy_function=shutil.copy2,
    )

config_lines: list[str] = []
config_values: dict[str, str] = {}
config_source = env_path if env_path.is_file() else env_example
if config_source.is_file():
    for raw in config_source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise SystemExit(f"backup=fail: invalid configuration key: {key!r}")
        config_lines.append(key)
        config_values[key] = value.strip().strip('"').strip("'")

config_keys = sorted(set(config_lines))
if not config_keys:
    raise SystemExit("backup=fail: no runtime configuration shape could be identified")
(staging / "config" / "env.keys").write_text(
    "# Key names only. Values and usable secrets are intentionally excluded.\n"
    + "\n".join(config_keys)
    + "\n",
    encoding="utf-8",
)

try:
    source_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=8,
    ).stdout.strip()
except (OSError, subprocess.SubprocessError):
    source_commit = "unknown"

metadata = {
    "format": "book-system-job-store",
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "source_root": str(root),
    "source_commit": source_commit,
    "included": ["books/jobs", "logs", "config/env.keys"],
    "excluded": [
        "runtime configuration values",
        "job .lock files",
        "books/cache",
        "books/outputs",
        "virtual environments",
    ],
}
(staging / "backup-metadata.json").write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

secret_values: list[tuple[str, bytes]] = []
for key, value in config_values.items():
    upper = key.upper()
    if not any(marker in upper for marker in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
        continue
    if len(value) < 8 or value.lower().startswith(("replace-with-", "change-this", "changeme")):
        continue
    secret_values.append((key, value.encode("utf-8")))

for path in staging.rglob("*"):
    if not path.is_file():
        continue
    raw = path.read_bytes()
    for key, secret in secret_values:
        if secret in raw:
            relative = path.relative_to(staging)
            raise SystemExit(
                f"backup=fail: configured secret value for {key} appears in staged file {relative}"
            )

job_count = sum(1 for path in (staging / "books" / "jobs").iterdir() if path.is_dir())
file_count = sum(1 for path in staging.rglob("*") if path.is_file())
print(f"backup-staged-jobs={job_count}")
print(f"backup-staged-files={file_count}")
print("backup-secret-scan=pass")
PY

tar -czf "$PARTIAL" -C "$TMP_DIR" book-system-backup
chmod 0600 "$PARTIAL"

python3 "$SCRIPT_DIR/validate_backup.py" "$PARTIAL"

mv -- "$PARTIAL" "$ARCHIVE"
trap - EXIT HUP INT TERM
rm -rf -- "$TMP_DIR"

printf 'backup-path=%s\n' "$ARCHIVE"
printf 'backup-bytes=%s\n' "$(stat -c '%s' "$ARCHIVE")"
printf 'backup-sha256=%s\n' "$(sha256sum "$ARCHIVE" | awk '{print $1}')"
echo "backup=pass"
