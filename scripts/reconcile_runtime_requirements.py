from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


EXACT_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[A-Za-z0-9._,-]+\])?==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)$"
)


class RequirementReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Requirement:
    raw: str
    identity: str
    has_extras: bool


@dataclass(frozen=True)
class ReconciliationPlan:
    current_sha256: str
    candidate_sha256: str
    policy: str
    additions: tuple[Requirement, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_identity(name: str, extras: str | None) -> str:
    package = re.sub(r"[-_.]+", "-", name).lower()
    if extras:
        values = [item.strip().lower() for item in extras[1:-1].split(",")]
        if not values or any(not item for item in values):
            raise RequirementReconciliationError("requirement extras are malformed")
    return package


def parse_requirements(path: Path) -> tuple[Requirement, ...]:
    if not path.is_file():
        raise RequirementReconciliationError("requirements file is unavailable")

    requirements: list[Requirement] = []
    seen_identities: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if any(token in line for token in (";", " @ ", "://")) or line.startswith("-"):
            raise RequirementReconciliationError(
                f"unsupported requirement syntax at line {line_number}"
            )
        match = EXACT_REQUIREMENT.fullmatch(line)
        if match is None:
            raise RequirementReconciliationError(
                f"requirement is not an exact simple pin at line {line_number}"
            )
        extras = match.group("extras")
        identity = _normalise_identity(match.group("name"), extras)
        if identity in seen_identities:
            raise RequirementReconciliationError(
                f"duplicate requirement identity at line {line_number}"
            )
        seen_identities.add(identity)
        requirements.append(
            Requirement(raw=line, identity=identity, has_extras=extras is not None)
        )
    if not requirements:
        raise RequirementReconciliationError("requirements file has no active requirements")
    return tuple(requirements)


def plan_reconciliation(current_path: Path, candidate_path: Path) -> ReconciliationPlan:
    current = parse_requirements(current_path)
    candidate = parse_requirements(candidate_path)
    current_by_id = {item.identity: item for item in current}
    candidate_by_id = {item.identity: item for item in candidate}

    for identity, requirement in current_by_id.items():
        candidate_requirement = candidate_by_id.get(identity)
        if candidate_requirement is None:
            raise RequirementReconciliationError(
                "candidate requirements remove an existing direct requirement"
            )
        if candidate_requirement.raw != requirement.raw:
            raise RequirementReconciliationError(
                "candidate requirements replace an existing direct requirement"
            )

    additions = tuple(
        requirement
        for requirement in candidate
        if requirement.identity not in current_by_id
    )
    if any(requirement.has_extras for requirement in additions):
        raise RequirementReconciliationError(
            "candidate additions with extras require a protected dependency migration"
        )
    return ReconciliationPlan(
        current_sha256=_sha256(current_path),
        candidate_sha256=_sha256(candidate_path),
        policy="additive" if additions else "unchanged",
        additions=additions,
    )


def _run_quiet(command: Sequence[str]) -> None:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RequirementReconciliationError(
            "runtime requirement command could not complete"
        ) from exc
    if completed.returncode != 0:
        raise RequirementReconciliationError("runtime requirement command failed")


def reconcile_runtime_requirements(
    *,
    current_path: Path,
    candidate_path: Path,
    python_bin: Path,
) -> ReconciliationPlan:
    if not python_bin.is_file():
        raise RequirementReconciliationError("production virtualenv Python is unavailable")

    plan = plan_reconciliation(current_path, candidate_path)
    if plan.additions:
        _run_quiet(
            [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--no-deps",
                *(item.raw for item in plan.additions),
            ]
        )
    _run_quiet(
        [
            str(python_bin),
            "-m",
            "pip",
            "check",
            "--disable-pip-version-check",
        ]
    )
    return plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile a production virtualenv with exact candidate requirements "
            "under the additive-only deployment policy."
        )
    )
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--python", dest="python_bin", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = reconcile_runtime_requirements(
            current_path=args.current.resolve(),
            candidate_path=args.candidate.resolve(),
            python_bin=args.python_bin.resolve(),
        )
    except RequirementReconciliationError as exc:
        print(f"runtime-requirements=fail: {exc}")
        return 1

    print("runtime-requirements=pass")
    print(f"current-requirements-sha256={plan.current_sha256}")
    print(f"candidate-requirements-sha256={plan.candidate_sha256}")
    print(f"requirements-policy={plan.policy}")
    print(f"requirements-additions={len(plan.additions)}")
    print("requirements-install=pass" if plan.additions else "requirements-install=skipped")
    print("pip-check=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
