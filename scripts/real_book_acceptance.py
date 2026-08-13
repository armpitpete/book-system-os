from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.services.artifact_readiness import ArtifactReadinessError
from app.services.job_queue import get_job
from app.services.real_book_acceptance import (
    evaluate_job_readiness,
    record_human_acceptance,
    record_production_validation,
    record_story_validation,
)


def _job(job_id: str) -> Path:
    job_dir = get_job(job_id)
    if job_dir is None:
        raise ValueError("Job not found")
    return job_dir


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description=(
            "Record and evaluate BOS-RDY-001 evidence for a real retained book job. "
            "This command never invents Story Validation, production validation, or human acceptance."
        )
    )
    sub = root.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Show current evidence and readiness states")
    show.add_argument("job_id")

    story = sub.add_parser(
        "story",
        help="Record an explicit external Story Validation result for the exact retained manuscript",
    )
    story.add_argument("job_id")
    story.add_argument("--state", choices=("pass", "fail"), required=True)
    story.add_argument("--evidence-id", required=True)
    story.add_argument("--decided-at")

    production = sub.add_parser(
        "production",
        help="Record an explicit production-validation result bound to the exact retained artifact",
    )
    production.add_argument("job_id")
    production.add_argument(
        "--artifact",
        choices=("pdf_standard", "pdf_nd", "epub", "docx"),
        required=True,
    )
    production.add_argument(
        "--readiness-class",
        choices=("production-valid", "digital-publication-ready", "print-ready"),
        required=True,
    )
    production.add_argument("--state", choices=("pass", "fail"), required=True)
    production.add_argument("--evidence-id", required=True)

    accept = sub.add_parser(
        "accept",
        help="Record a human accept/reject decision for the exact retained artifact",
    )
    accept.add_argument("job_id")
    accept.add_argument(
        "--artifact",
        choices=("pdf_standard", "pdf_nd", "epub", "docx"),
        required=True,
    )
    accept.add_argument(
        "--readiness-class",
        choices=("digital-publication-ready", "print-ready"),
        required=True,
    )
    accept.add_argument("--state", choices=("accepted", "rejected"), required=True)
    accept.add_argument("--evidence-id", required=True)
    accept.add_argument("--decided-at")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        job_dir = _job(args.job_id)
        if args.command == "show":
            _print(evaluate_job_readiness(job_dir))
            return 0
        if args.command == "story":
            result = record_story_validation(
                job_dir,
                state=args.state,
                evidence_id=args.evidence_id,
                decided_at=args.decided_at,
            )
        elif args.command == "production":
            result = record_production_validation(
                job_dir,
                artifact_type=args.artifact,
                readiness_class=args.readiness_class,
                state=args.state,
                evidence_id=args.evidence_id,
            )
        elif args.command == "accept":
            result = record_human_acceptance(
                job_dir,
                artifact_type=args.artifact,
                readiness_class=args.readiness_class,
                state=args.state,
                evidence_id=args.evidence_id,
                decided_at=args.decided_at,
            )
        else:  # pragma: no cover - argparse prevents this
            raise ValueError("Unknown command")

        _print(
            {
                "recorded": result,
                "readiness": evaluate_job_readiness(job_dir),
            }
        )
        return 0
    except (ArtifactReadinessError, ValueError) as exc:
        code = getattr(exc, "code", "acceptance-input-invalid")
        print(json.dumps({"ok": False, "code": code, "detail": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
