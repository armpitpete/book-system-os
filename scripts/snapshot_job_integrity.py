#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_RECORDS = (
    "input/book.md",
    "metadata.json",
    "status.json",
    "manifest.json",
)


class SnapshotError(RuntimeError):
    """Raised when a job cannot be used as rollback-integrity evidence."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid JSON record: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SnapshotError(f"JSON record is not an object: {path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_job(job_dir: Path) -> dict[str, Any]:
    job_dir = job_dir.resolve(strict=True)
    if job_dir.is_symlink() or not job_dir.is_dir():
        raise SnapshotError("job path must be a real directory")

    job_id = job_dir.name
    if not JOB_ID_RE.fullmatch(job_id):
        raise SnapshotError("job identifier is not safe")

    for relative in REQUIRED_RECORDS:
        path = job_dir / relative
        if not path.is_file() or path.is_symlink():
            raise SnapshotError(f"missing required regular file: {relative}")

    metadata = _load_object(job_dir / "metadata.json")
    status_record = _load_object(job_dir / "status.json")
    manifest = _load_object(job_dir / "manifest.json")

    if metadata.get("job_id") != job_id:
        raise SnapshotError("metadata job identifier does not match directory")
    if status_record.get("status") != "done":
        raise SnapshotError("rollback evidence job must be completed")

    manifest_outputs = manifest.get("outputs")
    if not isinstance(manifest_outputs, dict) or not manifest_outputs:
        raise SnapshotError("completed job manifest has no declared outputs")
    for filename in manifest_outputs.values():
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise SnapshotError("manifest contains an unsafe output filename")
        output = job_dir / "output" / filename
        if not output.is_file() or output.is_symlink() or output.stat().st_size <= 0:
            raise SnapshotError(f"declared output is missing or empty: {filename}")

    files: dict[str, dict[str, Any]] = {}
    for path in sorted(job_dir.rglob("*")):
        relative = path.relative_to(job_dir).as_posix()
        if relative == ".lock":
            continue
        if path.is_symlink():
            raise SnapshotError(f"symbolic link is not allowed: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SnapshotError(f"non-regular entry is not allowed: {relative}")
        file_stat = path.stat()
        files[relative] = {
            "bytes": file_stat.st_size,
            "mode": stat.S_IMODE(file_stat.st_mode),
            "sha256": _sha256(path),
        }

    return {
        "version": 1,
        "job_id": job_id,
        "status": "done",
        "state": status_record.get("state"),
        "files": files,
    }


def write_snapshot(job_dir: Path, output: Path) -> dict[str, Any]:
    snapshot = snapshot_job(job_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(output, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record an immutable integrity snapshot for one completed job."
    )
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        snapshot = write_snapshot(args.job_dir, args.output)
    except (OSError, SnapshotError) as exc:
        raise SystemExit(f"snapshot-error: {exc}") from exc
    print(
        json.dumps(
            {
                "job_id": snapshot["job_id"],
                "files": len(snapshot["files"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
