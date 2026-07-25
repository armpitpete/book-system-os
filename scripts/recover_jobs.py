#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.job_queue import get_job  # noqa: E402
from app.services.job_recovery import (  # noqa: E402
    RecoveryError,
    inspect_job_recovery,
    list_recovery_previews,
    recover_job,
)


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview and explicitly recover Book System jobs whose worker "
            "ownership is proven invalid."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview = subparsers.add_parser(
        "preview",
        help="Show active, abandoned, stale-lock or uncertain jobs without changing them",
    )
    preview.add_argument(
        "--job-id",
        help="Inspect one job instead of listing all recovery-relevant jobs",
    )

    recover = subparsers.add_parser(
        "recover",
        help="Apply one explicit audited recovery action",
    )
    recover.add_argument("job_id")
    recover.add_argument(
        "--to",
        required=True,
        choices=("queued", "failed"),
        dest="target",
        help="Return the job to queued or mark it failed",
    )
    recover.add_argument(
        "--operator",
        required=True,
        help="Operator identity written into status and event history",
    )
    recover.add_argument(
        "--reason",
        required=True,
        help="Concrete reason for the recovery decision",
    )

    return parser


def _resolve_job(job_id: str) -> Path:
    job = get_job(job_id)
    if job is None:
        raise RecoveryError(f"Job does not exist: {job_id}")
    return job


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "preview":
            if args.job_id:
                result: object = inspect_job_recovery(_resolve_job(args.job_id))
            else:
                result = {
                    "count": len(previews := list_recovery_previews()),
                    "jobs": previews,
                }
            _print_json(result)
            return 0

        result = recover_job(
            _resolve_job(args.job_id),
            target=args.target,
            operator=args.operator,
            reason=args.reason,
        )
        _print_json(result)
        return 0
    except RecoveryError as exc:
        print(f"recovery=refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
