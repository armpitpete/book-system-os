from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _prepare_surface(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository_root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "candidate" / "scripts"
    scripts.mkdir(parents=True)

    wrapper = scripts / "production_corpus_runtime_release_configured.sh"
    shutil.copyfile(
        repository_root / "scripts" / "production_corpus_runtime_release_configured.sh",
        wrapper,
    )

    base_launcher = scripts / "production_corpus_runtime_release.sh"
    base_launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        ": \"${CAPTURE_PATH:?}\"\n"
        "printf '%s\\n' \"$@\" >\"$CAPTURE_PATH\"\n",
        encoding="utf-8",
    )

    capture = tmp_path / "captured-arguments.txt"
    return wrapper, base_launcher, capture


def _run(wrapper: Path, capture: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CAPTURE_PATH"] = str(capture)
    return subprocess.run(
        ["bash", str(wrapper), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_configured_launcher_uses_protected_bind_port(tmp_path: Path) -> None:
    wrapper, _, capture = _prepare_surface(tmp_path)
    env_file = tmp_path / "env"
    env_file.write_text("BOOK_BIND_PORT='9123'\n", encoding="utf-8")

    completed = _run(
        wrapper,
        capture,
        "--env-file",
        str(env_file),
        "--repo-root",
        "/opt/book-system",
        "--expected-before",
        "a" * 40,
        "--target-commit",
        "b" * 40,
        "--confirm",
        f"DEPLOY {'b' * 40}",
    )

    assert completed.returncode == 0, completed.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert arguments[-2:] == ["--local-base-url", "http://127.0.0.1:9123"]
    assert arguments.count("--local-base-url") == 1


def test_configured_launcher_preserves_explicit_local_override(tmp_path: Path) -> None:
    wrapper, _, capture = _prepare_surface(tmp_path)

    completed = _run(
        wrapper,
        capture,
        "--env-file",
        str(tmp_path / "not-required"),
        "--local-base-url",
        "http://127.0.0.1:7444",
        "--target-commit",
        "b" * 40,
    )

    assert completed.returncode == 0, completed.stderr
    arguments = capture.read_text(encoding="utf-8").splitlines()
    assert arguments.count("--local-base-url") == 1
    index = arguments.index("--local-base-url")
    assert arguments[index + 1] == "http://127.0.0.1:7444"


def test_configured_launcher_rejects_invalid_port(tmp_path: Path) -> None:
    wrapper, _, capture = _prepare_surface(tmp_path)
    env_file = tmp_path / "env"
    env_file.write_text("BOOK_BIND_PORT=8088-not-a-port\n", encoding="utf-8")

    completed = _run(wrapper, capture, "--env-file", str(env_file))

    assert completed.returncode != 0
    assert "Could not resolve BOOK_BIND_PORT" in completed.stderr
    assert not capture.exists()


def test_configured_launcher_has_valid_shell_syntax() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    wrapper = repository_root / "scripts" / "production_corpus_runtime_release_configured.sh"

    completed = subprocess.run(
        ["bash", "-n", str(wrapper)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    text = wrapper.read_text(encoding="utf-8")
    assert "BOOK_BIND_PORT" in text
    assert "http://127.0.0.1:$BOOK_BIND_PORT" in text
    assert "127.0.0.1:8088" not in text
