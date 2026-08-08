from __future__ import annotations

import subprocess
from importlib import metadata
from pathlib import Path

import pytest

from scripts import image_holder_live_acceptance as image_acceptance
from scripts import reconcile_runtime_requirements as requirements


PRODUCTION_REQUIREMENTS_BEFORE_IMAGE_HOLDERS = (
    "fastapi==0.115.6",
    "uvicorn[standard]==0.34.0",
    "python-multipart==0.0.20",
    "pydantic==2.10.4",
    "jinja2==3.1.5",
)


def write_requirements(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_additive_requirement_plan_accepts_pillow(tmp_path: Path) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    write_requirements(current, "fastapi==0.115.6", "uvicorn[standard]==0.34.0")
    write_requirements(candidate, "fastapi==0.115.6", "uvicorn[standard]==0.34.0", "Pillow==12.3.0")
    plan = requirements.plan_reconciliation(current, candidate)
    assert plan.policy == "additive"
    assert [item.raw for item in plan.additions] == ["Pillow==12.3.0"]


def test_exact_production_to_current_candidate_is_only_pillow(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    current = tmp_path / "production-requirements.txt"
    write_requirements(current, *PRODUCTION_REQUIREMENTS_BEFORE_IMAGE_HOLDERS)
    plan = requirements.plan_reconciliation(current, root / "requirements.txt")
    assert plan.policy == "additive"
    assert [item.raw for item in plan.additions] == ["Pillow==12.3.0"]


def test_unchanged_requirement_plan_is_allowed(tmp_path: Path) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    write_requirements(current, "fastapi==0.115.6")
    write_requirements(candidate, "fastapi==0.115.6")
    plan = requirements.plan_reconciliation(current, candidate)
    assert plan.policy == "unchanged"
    assert plan.additions == ()


@pytest.mark.parametrize(
    ("current_lines", "candidate_lines", "message"),
    [
        (["fastapi==0.115.6"], ["fastapi==0.116.0"], "replace an existing direct requirement"),
        (["fastapi==0.115.6", "pydantic==2.10.4"], ["fastapi==0.115.6"], "remove an existing direct requirement"),
        (["uvicorn[standard]==0.34.0"], ["uvicorn[other]==0.34.0"], "replace an existing direct requirement"),
        (["fastapi==0.115.6"], ["fastapi==0.115.6", "new-package[extra]==1.0"], "protected dependency migration"),
    ],
)
def test_non_additive_requirement_changes_fail_closed(
    tmp_path: Path,
    current_lines: list[str],
    candidate_lines: list[str],
    message: str,
) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    write_requirements(current, *current_lines)
    write_requirements(candidate, *candidate_lines)
    with pytest.raises(requirements.RequirementReconciliationError, match=message):
        requirements.plan_reconciliation(current, candidate)


@pytest.mark.parametrize(
    "line",
    [
        "-r extra.txt",
        "--index-url https://example.invalid/simple",
        "-e .",
        "package @ https://example.invalid/package.whl",
        "https://example.invalid/package.whl",
        "package>=1.0",
        "package==1.0; python_version > '3.11'",
    ],
)
def test_unsupported_requirement_syntax_fails_closed(tmp_path: Path, line: str) -> None:
    path = tmp_path / "requirements.txt"
    write_requirements(path, line)
    with pytest.raises(requirements.RequirementReconciliationError):
        requirements.parse_requirements(path)


def test_duplicate_requirement_identity_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "requirements.txt"
    write_requirements(path, "Pillow==12.3.0", "pillow==12.3.0")
    with pytest.raises(requirements.RequirementReconciliationError, match="duplicate requirement identity"):
        requirements.parse_requirements(path)


def test_duplicate_requirement_with_different_extras_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "requirements.txt"
    write_requirements(path, "uvicorn[standard]==0.34.0", "uvicorn[other]==0.34.0")
    with pytest.raises(requirements.RequirementReconciliationError, match="duplicate requirement identity"):
        requirements.parse_requirements(path)


def test_reconciliation_installs_only_absent_additions_then_runs_pip_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    python_bin = tmp_path / "python"
    python_bin.write_text("", encoding="utf-8")
    write_requirements(current, "fastapi==0.115.6")
    write_requirements(candidate, "fastapi==0.115.6", "Pillow==12.3.0")
    commands: list[list[str]] = []

    def not_installed(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    def fake_run(
        command: list[str],
        *,
        check: bool,
        stdout: int,
        stderr: int,
        timeout: int,
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(requirements.metadata, "version", not_installed)
    monkeypatch.setattr(requirements.subprocess, "run", fake_run)
    plan = requirements.reconcile_runtime_requirements(
        current_path=current,
        candidate_path=candidate,
        python_bin=python_bin,
    )
    assert plan.policy == "additive"
    assert commands[0][-2:] == ["--no-deps", "Pillow==12.3.0"]
    assert commands[1][-2:] == ["check", "--disable-pip-version-check"]


def test_existing_same_version_addition_is_verified_without_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    python_bin = tmp_path / "python"
    python_bin.write_text("", encoding="utf-8")
    write_requirements(current, "fastapi==0.115.6")
    write_requirements(candidate, "fastapi==0.115.6", "Pillow==12.3.0")
    commands: list[list[str]] = []

    monkeypatch.setattr(requirements.metadata, "version", lambda name: "12.3.0")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(requirements.subprocess, "run", fake_run)
    requirements.reconcile_runtime_requirements(
        current_path=current,
        candidate_path=candidate,
        python_bin=python_bin,
    )
    assert len(commands) == 1
    assert commands[0][-2:] == ["check", "--disable-pip-version-check"]


def test_existing_different_version_addition_requires_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    python_bin = tmp_path / "python"
    python_bin.write_text("", encoding="utf-8")
    write_requirements(current, "fastapi==0.115.6")
    write_requirements(candidate, "fastapi==0.115.6", "Pillow==12.3.0")
    monkeypatch.setattr(requirements.metadata, "version", lambda name: "11.0.0")

    with pytest.raises(requirements.RequirementReconciliationError, match="replace an installed distribution"):
        requirements.reconcile_runtime_requirements(
            current_path=current,
            candidate_path=candidate,
            python_bin=python_bin,
        )


def test_requirement_install_failure_is_reported_without_command_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    python_bin = tmp_path / "python"
    python_bin.write_text("", encoding="utf-8")
    write_requirements(current, "fastapi==0.115.6")
    write_requirements(candidate, "fastapi==0.115.6", "Pillow==12.3.0")

    def not_installed(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(["pip"], 1)

    monkeypatch.setattr(requirements.metadata, "version", not_installed)
    monkeypatch.setattr(requirements.subprocess, "run", fake_run)
    with pytest.raises(requirements.RequirementReconciliationError, match="runtime requirement command failed"):
        requirements.reconcile_runtime_requirements(
            current_path=current,
            candidate_path=candidate,
            python_bin=python_bin,
        )


def test_release_wrapper_reconciles_requirements_before_base_deployment() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "production_current_main_release.sh").read_text(encoding="utf-8")
    reconcile_marker = '"$python_bin" "$REQUIREMENTS_RECONCILER"'
    base_marker = 'bash "$BASE_LAUNCHER"'
    assert reconcile_marker in source
    assert base_marker in source
    assert source.index(reconcile_marker) < source.index(base_marker)
    assert '"$python_bin" "$REPO_ROOT/scripts/image_holder_live_acceptance.py"' in source


def test_image_holder_runtime_smoke_uses_real_pipeline() -> None:
    root = Path(__file__).resolve().parents[1]
    result = image_acceptance.check_image_holder_runtime(root)
    assert result["pillow_version"] == "12.3.0"
    assert result["representative_holder"] == "pass"
    assert result["low_resolution_fail_closed"] == "pass"
    assert result["remote_holder_fail_closed"] == "pass"
