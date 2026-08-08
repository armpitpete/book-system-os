from __future__ import annotations

import os
import stat
import subprocess
import venv
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RECONCILER = REPO_ROOT / "scripts" / "reconcile_runtime_requirements.py"
PACKAGE_NAME = "book-system-permission-fixture"
PACKAGE_VERSION = "1.0.0"
WHEEL_NAME = "book_system_permission_fixture-1.0.0-py3-none-any.whl"


def _write_requirements(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture_wheel(directory: Path) -> Path:
    directory.mkdir()
    wheel = directory / WHEEL_NAME
    dist_info = "book_system_permission_fixture-1.0.0.dist-info"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "book_system_permission_fixture/__init__.py",
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


def _site_packages(python_bin: Path) -> Path:
    completed = subprocess.run(
        [
            str(python_bin),
            "-c",
            "import site; print(site.getsitepackages()[0])",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return Path(completed.stdout.strip())


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_runtime_install_overrides_private_release_umask(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    _build_fixture_wheel(wheelhouse)

    runtime = tmp_path / "runtime"
    venv.EnvBuilder(with_pip=True, clear=True).create(runtime)
    python_bin = runtime / "bin" / "python"

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
        umask=0o077,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "runtime-requirements=pass" in completed.stdout
    assert "requirements-service-readability=verified" in completed.stdout

    site_packages = _site_packages(python_bin)
    package_dir = site_packages / "book_system_permission_fixture"
    package_file = package_dir / "__init__.py"
    dist_info = site_packages / "book_system_permission_fixture-1.0.0.dist-info"
    metadata_file = dist_info / "METADATA"

    assert _mode(package_dir) & stat.S_IXOTH
    assert _mode(package_dir) & stat.S_IROTH
    assert _mode(package_file) & stat.S_IROTH
    assert _mode(dist_info) & stat.S_IXOTH
    assert _mode(dist_info) & stat.S_IROTH
    assert _mode(metadata_file) & stat.S_IROTH
