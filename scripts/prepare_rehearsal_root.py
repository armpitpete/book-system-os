#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import sys
from datetime import datetime, timezone
from pathlib import Path


def validate_target(target: Path, production_root: Path) -> tuple[Path, Path]:
    if not target.is_absolute():
        raise ValueError("rehearsal root must be absolute")
    resolved_target = target.resolve(strict=False)
    resolved_production = production_root.resolve(strict=True)
    if resolved_target == resolved_production or resolved_production in resolved_target.parents:
        raise ValueError("rehearsal root must be outside production")
    if resolved_target.exists():
        raise ValueError("rehearsal root already exists")
    return resolved_target, resolved_production


def create_rehearsal_root(
    target: Path,
    *,
    service_user: str,
    service_group: str,
    production_root: Path,
) -> dict[str, object]:
    target, production_root = validate_target(target, production_root)
    uid = pwd.getpwnam(service_user).pw_uid
    gid = grp.getgrnam(service_group).gr_gid

    target.mkdir(parents=True, mode=0o750)
    os.chown(target, 0, gid)
    os.chmod(target, 0o750)

    service_directories = [
        target / "books",
        target / "books" / "jobs",
        target / "logs",
    ]
    root_directories = [
        target / "config-shape",
        target / "evidence",
    ]

    for directory in service_directories:
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, uid, gid)
        os.chmod(directory, 0o750)

    for directory in root_directories:
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, 0, gid)
        os.chmod(directory, 0o750 if directory.name == "config-shape" else 0o700)

    report = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rehearsal_root": str(target),
        "production_root": str(production_root),
        "service_user": service_user,
        "service_group": service_group,
        "contains_credentials": False,
        "contains_production_jobs": False,
        "purpose": "isolated production-like acceptance fixtures",
    }
    marker = target / "rehearsal-root.json"
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chown(marker, 0, gid)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an isolated service-owned rehearsal root without production data."
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--production-root", default=Path("/opt/book-system"), type=Path)
    parser.add_argument("--service-user", default="www-data")
    parser.add_argument("--service-group", default="www-data")
    parser.add_argument("--confirm", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        print("ERROR: run as root", file=sys.stderr)
        return 2
    if args.confirm != "create-isolated-rehearsal-root":
        print("ERROR: missing exact rehearsal-root confirmation", file=sys.stderr)
        return 2
    try:
        report = create_rehearsal_root(
            args.root,
            service_user=args.service_user,
            service_group=args.service_group,
            production_root=args.production_root,
        )
    except (KeyError, OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
