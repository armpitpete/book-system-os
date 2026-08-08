from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from importlib import metadata
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
    version: str
    has_extras: bool


@dataclass(frozen=True)
class StagedWheel:
    filename: str
    sha256: str


@dataclass(frozen=True)
class ReconciliationPlan:
    current_sha256: str
    candidate_sha256: str
    policy: str
    additions: tuple[Requirement, ...]
    staged_wheels: tuple[StagedWheel, ...] = ()


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
            Requirement(
                raw=line,
                identity=identity,
                version=match.group("version"),
                has_extras=extras is not None,
            )
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


def _run_quiet(command: Sequence[str], *, failure_message: str) -> None:
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
            f"{failure_message}: command could not complete"
        ) from exc
    if completed.returncode != 0:
        raise RequirementReconciliationError(failure_message)


def _additions_to_install(plan: ReconciliationPlan) -> tuple[Requirement, ...]:
    missing: list[Requirement] = []
    for requirement in plan.additions:
        try:
            installed_version = metadata.version(requirement.identity)
        except metadata.PackageNotFoundError:
            missing.append(requirement)
            continue
        if installed_version != requirement.version:
            raise RequirementReconciliationError(
                "candidate addition would replace an installed distribution"
            )
    return tuple(missing)


def _stage_binary_wheels(
    *,
    python_bin: Path,
    requirements: tuple[Requirement, ...],
    stage_root: Path,
) -> tuple[tuple[Path, ...], tuple[StagedWheel, ...]]:
    wheel_paths: list[Path] = []
    evidence: list[StagedWheel] = []

    for requirement in requirements:
        requirement_stage = stage_root / requirement.identity
        requirement_stage.mkdir(mode=0o700)
        _run_quiet(
            [
                str(python_bin),
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--no-input",
                "--no-deps",
                "--only-binary=:all:",
                "--dest",
                str(requirement_stage),
                requirement.raw,
            ],
            failure_message="runtime requirement wheel download failed",
        )
        files = sorted(path for path in requirement_stage.iterdir() if path.is_file())
        if len(files) != 1 or files[0].suffix.lower() != ".whl":
            raise RequirementReconciliationError(
                "runtime requirement did not resolve to exactly one binary wheel"
            )
        wheel = files[0]
        wheel_paths.append(wheel)
        evidence.append(StagedWheel(filename=wheel.name, sha256=_sha256(wheel)))

    return tuple(wheel_paths), tuple(evidence)


def _verify_additions_installed(requirements: tuple[Requirement, ...]) -> None:
    for requirement in requirements:
        try:
            installed_version = metadata.version(requirement.identity)
        except metadata.PackageNotFoundError as exc:
            raise RequirementReconciliationError(
                "installed additive requirement is unavailable after local wheel install"
            ) from exc
        if installed_version != requirement.version:
            raise RequirementReconciliationError(
                "installed additive requirement version does not match candidate"
            )


def reconcile_runtime_requirements(
    *,
    current_path: Path,
    candidate_path: Path,
    python_bin: Path,
) -> ReconciliationPlan:
    if not python_bin.is_file():
        raise RequirementReconciliationError("production virtualenv Python is unavailable")

    plan = plan_reconciliation(current_path, candidate_path)
    to_install = _additions_to_install(plan)
    staged_wheels: tuple[StagedWheel, ...] = ()

    if to_install:
        with tempfile.TemporaryDirectory(
            prefix="book-system-runtime-wheels-",
        ) as raw_stage_root:
            stage_root = Path(raw_stage_root)
            os.chmod(stage_root, 0o700)
            wheel_paths, staged_wheels = _stage_binary_wheels(
                python_bin=python_bin,
                requirements=to_install,
                stage_root=stage_root,
            )
            _run_quiet(
                [
                    str(python_bin),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--no-index",
                    "--no-deps",
                    *(str(path) for path in wheel_paths),
                ],
                failure_message="runtime requirement local wheel install failed",
            )
            _verify_additions_installed(to_install)

    _run_quiet(
        [
            str(python_bin),
            "-m",
            "pip",
            "check",
            "--disable-pip-version-check",
        ],
        failure_message="runtime requirement pip check failed",
    )
    return replace(plan, staged_wheels=staged_wheels)


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
    print(f"staged-wheel-count={len(plan.staged_wheels)}")
    for wheel in plan.staged_wheels:
        print(f"staged-wheel={wheel.filename} sha256={wheel.sha256}")
    print("requirements-environment=verified")
    print("pip-check=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
