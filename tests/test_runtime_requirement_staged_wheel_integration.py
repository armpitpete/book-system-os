from __future__ import annotations

import hashlib
import os
import subprocess
import venv
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RECONCILER = REPO_ROOT / "scripts" / "reconcile_runtime_requirements.py"
PACKAGE_NAME = "book-system-fixture"
PACKAGE_VERSION = "1.0.0"
WHEEL_NAME = "book_system_fixture-1.0.0-py3-none-any.whl"


def _write_requirements(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture_wheel(directory: Path) -> Path:
    directory.mkdir()
    wheel = directory / WHEEL_NAME
    dist_info = "book_system_fixture-1.0.0.dist-info"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "book_system_fixture/__init__.py",
            '__version__ = "1.0.0"\n',
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: book-system-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n",
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {PACKAGE_NAME}\n"
            f"Version: {PACKAGE_VERSION}\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return wheel


def test_staged_wheel_reconciliation_runs_end_to_end_without_network(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheel = _build_fixture_wheel(wheelhouse)
    expected_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=True, clear=True).create(runtime)
    python_bin = runtime / "bin" / "python"
    assert python_bin.is_file()

    current = tmp_path / "current.txt"
    candidate = tmp_path / "candidate.txt"
    _write_requirements(current, "baseline==1.0.0")
    _write_requirements(
        candidate,
        "baseline==1.0.0",
        f"{PACKAGE_NAME}=={PACKAGE_VERSION}",
    )

    env = os.environ.copy()
    env["PIP_NO_INDEX"] = "1"
    env["PIP_FIND_LINKS"] = str(wheelhouse)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    completed = subprocess.run(
        [
            str(python_bin),
            str(RECONCILER),
            "--current",
            str(current),
            "--candidate",
            str(candidate),
            "--python",
            str(python_bin),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "runtime-requirements=pass" in completed.stdout
    assert "requirements-policy=additive" in completed.stdout
    assert "requirements-additions=1" in completed.stdout
    assert "staged-wheel-count=1" in completed.stdout
    assert f"staged-wheel={WHEEL_NAME} sha256={expected_digest}" in completed.stdout
    assert "pip-check=pass" in completed.stdout

    verified = subprocess.run(
        [
            str(python_bin),
            "-c",
            (
                "from importlib import metadata; "
                f"print(metadata.version('{PACKAGE_NAME}'))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert verified.returncode == 0
    assert verified.stdout.strip() == PACKAGE_VERSION
