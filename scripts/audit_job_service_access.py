#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class AccessRequirement:
    path: Path
    kind: str
    modes: tuple[str, ...]


@dataclass(frozen=True)
class AccessFailure:
    requirement: AccessRequirement
    mode: str


Runner = Callable[[str, Path, str], bool]


def requirements_for_job_store(jobs_root: Path) -> Iterable[AccessRequirement]:
    root = jobs_root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("job store must be a real directory")

    yield AccessRequirement(root, "job-store-directory", ("r", "w", "x"))

    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("job store contains a symbolic link")
        if path.is_dir():
            yield AccessRequirement(path, "directory", ("r", "w", "x"))
            continue
        if not path.is_file():
            raise ValueError("job store contains a non-regular entry")

        modes = ["r"]
        if path.suffix in {".jsonl", ".log"}:
            modes.append("w")
        yield AccessRequirement(path, "file", tuple(modes))


def runuser_access(user: str, path: Path, mode: str) -> bool:
    if mode not in {"r", "w", "x"}:
        raise ValueError(f"unsupported access mode: {mode}")
    result = subprocess.run(
        ["runuser", "-u", user, "--", "test", f"-{mode}", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def audit_job_store(
    jobs_root: Path,
    *,
    service_user: str,
    runner: Runner = runuser_access,
) -> tuple[list[AccessRequirement], list[AccessFailure]]:
    requirements = list(requirements_for_job_store(jobs_root))
    failures: list[AccessFailure] = []
    for requirement in requirements:
        for mode in requirement.modes:
            if not runner(service_user, requirement.path, mode):
                failures.append(AccessFailure(requirement, mode))
    return requirements, failures


def build_report(
    jobs_root: Path,
    requirements: list[AccessRequirement],
    failures: list[AccessFailure],
    *,
    include_paths: bool,
) -> dict[str, object]:
    root = jobs_root.resolve(strict=True)
    job_ids = {
        requirement.path.relative_to(root).parts[0]
        for requirement in requirements
        if requirement.path != root
    }
    categories = Counter(
        f"{failure.requirement.kind}:{failure.mode}" for failure in failures
    )
    report: dict[str, object] = {
        "version": 1,
        "status": "pass" if not failures else "fail",
        "jobs_checked": len(job_ids),
        "paths_checked": len(requirements),
        "access_checks": sum(len(item.modes) for item in requirements),
        "failure_count": len(failures),
        "failure_categories": dict(sorted(categories.items())),
    }
    if include_paths:
        report["failures"] = [
            {
                "path": failure.requirement.path.relative_to(root).as_posix(),
                "kind": failure.requirement.kind,
                "mode": failure.mode,
            }
            for failure in failures
        ]
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit retained job-store access as the production service user."
    )
    parser.add_argument("--jobs-root", required=True, type=Path)
    parser.add_argument("--service-user", default="www-data")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--include-paths",
        action="store_true",
        help="Include relative failing paths; use only in private evidence.",
    )
    return parser.parse_args(argv)


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        requirements, failures = audit_job_store(
            args.jobs_root,
            service_user=args.service_user,
        )
        report = build_report(
            args.jobs_root,
            requirements,
            failures,
            include_paths=args.include_paths,
        )
        if args.output is not None:
            write_report(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return 0 if not failures else 1
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "version": 1,
                    "status": "error",
                    "error": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
