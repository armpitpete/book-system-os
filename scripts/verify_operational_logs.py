#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

WORKER_HEARTBEAT = "worker-heartbeat.json"
VALID_WORKER_STATES = {"starting", "idle", "running"}


class OperationalLogVerificationError(RuntimeError):
    """Raised when preserved operational logs or mutable state are invalid."""


def _safe_path(root: Path, relative: str) -> Path:
    candidate = PurePosixPath(relative)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise OperationalLogVerificationError(
            f"unsafe operational-log path: {relative!r}"
        )
    return root.joinpath(*candidate.parts)


def _parse_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OperationalLogVerificationError(
            f"worker heartbeat {field} is missing"
        )
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OperationalLogVerificationError(
            f"worker heartbeat {field} is invalid"
        ) from exc
    return value


def validate_worker_heartbeat(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise OperationalLogVerificationError(
            "worker heartbeat is missing or unsafe"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalLogVerificationError(
            "worker heartbeat is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise OperationalLogVerificationError(
            "worker heartbeat is not an object"
        )
    if payload.get("version") != 1:
        raise OperationalLogVerificationError(
            "worker heartbeat version is unsupported"
        )
    worker_id = payload.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise OperationalLogVerificationError(
            "worker heartbeat worker_id is missing"
        )
    state = payload.get("state")
    if state not in VALID_WORKER_STATES:
        raise OperationalLogVerificationError(
            "worker heartbeat state is invalid"
        )
    started_at = _parse_timestamp(payload.get("started_at"), "started_at")
    heartbeat_at = _parse_timestamp(payload.get("heartbeat_at"), "heartbeat_at")
    return {
        "version": 1,
        "worker_id_present": True,
        "state": state,
        "started_at": started_at,
        "heartbeat_at": heartbeat_at,
    }


def verify_operational_logs(
    *,
    before_path: Path,
    logs_root: Path,
) -> dict[str, Any]:
    try:
        snapshot = json.loads(before_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalLogVerificationError(
            "operational-log snapshot is unreadable"
        ) from exc
    files = snapshot.get("files") if isinstance(snapshot, dict) else None
    if not isinstance(files, dict):
        raise OperationalLogVerificationError(
            "operational-log snapshot has no files object"
        )

    root = logs_root.resolve(strict=True)
    append_only_count = 0
    mutable_state: dict[str, Any] = {}

    for relative, record in sorted(files.items()):
        if not isinstance(relative, str) or not isinstance(record, dict):
            raise OperationalLogVerificationError(
                "operational-log snapshot record is invalid"
            )
        path = _safe_path(root, relative)
        if relative == WORKER_HEARTBEAT:
            mutable_state = validate_worker_heartbeat(path)
            continue
        if not path.is_file() or path.is_symlink():
            raise OperationalLogVerificationError(
                f"pre-existing operational log disappeared: {relative}"
            )
        try:
            size = int(record["bytes"])
            expected_sha = str(record["sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationalLogVerificationError(
                f"operational-log snapshot record is invalid: {relative}"
            ) from exc
        if size < 0:
            raise OperationalLogVerificationError(
                f"operational-log snapshot size is invalid: {relative}"
            )
        with path.open("rb") as handle:
            prefix = handle.read(size)
        actual_sha = hashlib.sha256(prefix).hexdigest()
        if len(prefix) != size or actual_sha != expected_sha:
            raise OperationalLogVerificationError(
                f"pre-existing operational log was replaced or truncated: {relative}"
            )
        append_only_count += 1

    if WORKER_HEARTBEAT in files and not mutable_state:
        raise OperationalLogVerificationError(
            "worker heartbeat mutable-state validation did not run"
        )

    return {
        "version": 1,
        "append_only_logs_preserved": append_only_count,
        "mutable_state_files_validated": (
            [WORKER_HEARTBEAT] if WORKER_HEARTBEAT in files else []
        ),
        "worker_heartbeat": mutable_state,
    }


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify append-only operational logs while validating the "
            "atomically replaced worker heartbeat as mutable state."
        )
    )
    parser.add_argument("before_snapshot", type=Path)
    parser.add_argument("logs_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = verify_operational_logs(
            before_path=args.before_snapshot,
            logs_root=args.logs_root,
        )
        _write_json_exclusive(args.output, report)
    except (OperationalLogVerificationError, OSError) as exc:
        print(f"operational-log-verification=fail: {exc}", file=sys.stderr)
        return 1
    print(
        "operational-log-verification=pass "
        f"append-only={report['append_only_logs_preserved']} "
        f"mutable-state={len(report['mutable_state_files_validated'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
