from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.utils.atomic_files import atomic_write_json, atomic_write_text


pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX file permission modes are required"
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("initial_mode", [0o000, 0o600, 0o640])
def test_atomic_write_text_preserves_existing_mode(
    tmp_path: Path, initial_mode: int
) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("original", encoding="utf-8")
    target.chmod(initial_mode)

    atomic_write_text(target, "replacement")

    observed_mode = _mode(target)
    target.chmod(0o600)  # Allow non-root runners to inspect restrictive output.
    assert observed_mode == initial_mode
    assert target.read_text(encoding="utf-8") == "replacement"


def test_atomic_write_text_new_file_defaults_to_0644(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"

    atomic_write_text(target, "created")

    assert _mode(target) == 0o644
    assert target.read_text(encoding="utf-8") == "created"


@pytest.mark.parametrize("explicit_mode", [0o000, 0o600])
def test_atomic_write_text_honours_explicit_mode(
    tmp_path: Path, explicit_mode: int
) -> None:
    target = tmp_path / "explicit.txt"
    target.write_text("original", encoding="utf-8")
    target.chmod(0o640)

    atomic_write_text(target, "replacement", mode=explicit_mode)

    observed_mode = _mode(target)
    target.chmod(0o600)
    assert observed_mode == explicit_mode
    assert target.read_text(encoding="utf-8") == "replacement"


def test_atomic_write_json_preserves_existing_zero_mode(tmp_path: Path) -> None:
    target = tmp_path / "restricted.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o000)

    atomic_write_json(target, {"key": "value"})

    observed_mode = _mode(target)
    target.chmod(0o600)
    assert observed_mode == 0o000
    assert '"key": "value"' in target.read_text(encoding="utf-8")
