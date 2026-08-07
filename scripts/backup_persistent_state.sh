#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

usage() {
  cat <<'EOF'
Usage: bash scripts/backup_persistent_state.sh [--root PATH] ARCHIVE.tar.gz

Create a validated Book System OS persistent-state backup.
This reuses the established job-store backup, adds Revision Studio durable state,
reruns secret scanning, validates the combined archive, and performs a clean
restore rehearsal before publishing the requested archive.
EOF
}

ROOT="${BOOK_SYSTEM_ROOT:-}"
if [[ "${1:-}" == "--root" ]]; then
  [[ "$#" -ge 3 ]] || { usage >&2; exit 2; }
  ROOT="$2"
  shift 2
fi
[[ "$#" -eq 1 ]] || { usage >&2; exit 2; }
ARCHIVE="$1"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
if [[ -z "$ROOT" ]]; then
  ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
fi
ROOT="$(CDPATH= cd -- "$ROOT" && pwd -P)"

[[ -f "$SCRIPT_DIR/backup_job_store.sh" ]] || {
  echo "persistent-backup=fail: backup_job_store.sh is unavailable" >&2
  exit 1
}
[[ -f "$SCRIPT_DIR/validate_backup.py" ]] || {
  echo "persistent-backup=fail: validate_backup.py is unavailable" >&2
  exit 1
}
[[ -d "$ROOT/books/jobs" ]] || {
  echo "persistent-backup=fail: missing job store: $ROOT/books/jobs" >&2
  exit 1
}

ARCHIVE_DIR="$(dirname -- "$ARCHIVE")"
ARCHIVE_NAME="$(basename -- "$ARCHIVE")"
mkdir -p -- "$ARCHIVE_DIR"
ARCHIVE_DIR="$(CDPATH= cd -- "$ARCHIVE_DIR" && pwd -P)"
ARCHIVE="$ARCHIVE_DIR/$ARCHIVE_NAME"
[[ ! -e "$ARCHIVE" ]] || {
  echo "persistent-backup=fail: destination already exists: $ARCHIVE" >&2
  exit 1
}

TMP_DIR="$(mktemp -d "$ARCHIVE_DIR/.book-system-persistent-backup.XXXXXX")"
PARTIAL="$ARCHIVE_DIR/.$ARCHIVE_NAME.partial.$$"
cleanup() {
  rm -rf -- "$TMP_DIR"
  rm -f -- "$PARTIAL"
}
trap cleanup EXIT HUP INT TERM

JOB_ARCHIVE="$TMP_DIR/job-store.tar.gz"
STAGING="$TMP_DIR/staging"
RESTORE_ROOT="$TMP_DIR/restore"
mkdir -p -- "$STAGING"

bash "$SCRIPT_DIR/backup_job_store.sh" --root "$ROOT" "$JOB_ARCHIVE"
tar -xzf "$JOB_ARCHIVE" -C "$STAGING"

python3 - "$ROOT" "$STAGING/book-system-backup" <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
staging = Path(sys.argv[2]).resolve()
source = root / "books" / "revisions"
destination = staging / "books" / "revisions"
destination.mkdir(parents=True, exist_ok=True)


def reject_unsafe_tree(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise SystemExit(f"persistent-backup=fail: invalid revision store: {path}")
    for current_root, directories, files in os.walk(path, followlinks=False):
        current = Path(current_root)
        for name in [*directories, *files]:
            candidate = current / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise SystemExit(
                    f"persistent-backup=fail: symbolic links are not allowed: {candidate}"
                )
            if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise SystemExit(
                    f"persistent-backup=fail: unsupported revision-store entry: {candidate}"
                )


reject_unsafe_tree(source)
if source.is_dir():
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        copy_function=shutil.copy2,
    )

metadata_path = staging / "backup-metadata.json"
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
if not isinstance(metadata, dict):
    raise SystemExit("persistent-backup=fail: backup metadata is invalid")
included = metadata.get("included")
if not isinstance(included, list):
    raise SystemExit("persistent-backup=fail: backup metadata included list is invalid")
if "books/revisions" not in included:
    included.append("books/revisions")
metadata["included"] = included
metadata["persistent_state_extension"] = 1
metadata_path.write_text(
    json.dumps(metadata, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

config_source = root / "config" / "env"
if not config_source.is_file():
    config_source = root / "config" / "env.example"
secret_values: list[tuple[str, bytes]] = []
if config_source.is_file():
    for raw in config_source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        upper = key.upper()
        if not any(marker in upper for marker in ("KEY", "PASSWORD", "SECRET", "TOKEN")):
            continue
        value = value.strip().strip('"').strip("'")
        if len(value) < 8 or value.lower().startswith(
            ("replace-with-", "change-this", "changeme")
        ):
            continue
        secret_values.append((key, value.encode("utf-8")))

if secret_values:
    longest = max(len(secret) for _, secret in secret_values)
    for path in staging.rglob("*"):
        if not path.is_file():
            continue
        tail = b""
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                window = tail + chunk
                for key, secret in secret_values:
                    if secret in window:
                        relative = path.relative_to(staging)
                        raise SystemExit(
                            "persistent-backup=fail: configured secret value for "
                            f"{key} appears in staged file {relative}"
                        )
                tail = window[-(longest - 1):] if longest > 1 else b""

revision_files = sum(
    1 for path in destination.rglob("*") if path.is_file() and path.name != ".gitkeep"
)
print(f"persistent-backup-revision-files={revision_files}")
print("persistent-backup-secret-scan=pass")
PY

tar -czf "$PARTIAL" -C "$STAGING" book-system-backup
chmod 0600 "$PARTIAL"
python3 "$SCRIPT_DIR/validate_backup.py" "$PARTIAL"
python3 "$SCRIPT_DIR/validate_backup.py" "$PARTIAL" --restore-root "$RESTORE_ROOT"

python3 - "$ROOT/books/revisions" "$RESTORE_ROOT/books/revisions" <<'PY'
from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path


def snapshot(root: Path) -> list[tuple[str, str, int, str | None]]:
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise SystemExit(f"persistent-backup=fail: invalid revision root: {root}")
    result: list[tuple[str, str, int, str | None]] = []
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        for name in sorted(directories):
            path = current / name
            if path.is_symlink():
                raise SystemExit(f"persistent-backup=fail: symlink in revision root: {path}")
            relative = path.relative_to(root).as_posix()
            result.append((relative, "directory", stat.S_IMODE(path.stat().st_mode), None))
        for name in sorted(files):
            if name == ".gitkeep":
                continue
            path = current / name
            if path.is_symlink() or not path.is_file():
                raise SystemExit(f"persistent-backup=fail: unsafe revision file: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            relative = path.relative_to(root).as_posix()
            result.append((relative, "file", stat.S_IMODE(path.stat().st_mode), digest))
    return sorted(result)

source = snapshot(Path(sys.argv[1]))
restored = snapshot(Path(sys.argv[2]))
if source != restored:
    raise SystemExit("persistent-backup=fail: restored Revision Studio state differs")
print("persistent-backup-revision-restore=pass")
PY

mv -- "$PARTIAL" "$ARCHIVE"
trap - EXIT HUP INT TERM
rm -rf -- "$TMP_DIR"

printf 'persistent-backup-path=%s\n' "$ARCHIVE"
printf 'persistent-backup-bytes=%s\n' "$(stat -c '%s' "$ARCHIVE")"
printf 'persistent-backup-sha256=%s\n' "$(sha256sum "$ARCHIVE" | awk '{print $1}')"
echo "persistent-backup=pass"
