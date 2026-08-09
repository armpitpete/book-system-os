from __future__ import annotations

from pathlib import Path

import pytest

from app.services import resource_limits
from scripts import production_current_main_preflight as preflight


def test_validate_sha_requires_full_lowercase_sha() -> None:
    assert preflight.validate_sha("a" * 40, "target") == "a" * 40
    for value in ("a" * 39, "A" * 40, "g" * 40, " main "):
        with pytest.raises(preflight.PreflightError, match="full lowercase SHA-1"):
            preflight.validate_sha(value, "target")


def test_selected_env_reads_only_nonsecret_capacity_settings(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(
        "\n".join(
            [
                "BOOK_API_KEY=super-secret",
                "BOOK_ADMIN_PASSWORD=also-secret",
                "BOOK_BIND_PORT=8080",
                "BOOK_READINESS_MIN_FREE_BYTES=123",
                "BOOK_MAX_TOTAL_STORAGE_BYTES=456",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    values = preflight.selected_env(env_file)
    assert values == {
        "BOOK_BIND_PORT": "8080",
        "BOOK_READINESS_MIN_FREE_BYTES": "123",
        "BOOK_MAX_TOTAL_STORAGE_BYTES": "456",
    }
    assert "secret" not in repr(values)


def test_storage_default_matches_runtime_and_applies_when_unset() -> None:
    assert preflight.MAX_TOTAL_STORAGE_DEFAULT == resource_limits.DEFAULT_MAX_TOTAL_STORAGE_BYTES
    assert preflight.positive_int(
        {}, "BOOK_MAX_TOTAL_STORAGE_BYTES", preflight.MAX_TOTAL_STORAGE_DEFAULT
    ) == resource_limits.DEFAULT_MAX_TOTAL_STORAGE_BYTES


def test_selected_env_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("BOOK_BIND_PORT=8080\n", encoding="utf-8")
    link = tmp_path / "env"
    link.symlink_to(target)
    with pytest.raises(preflight.PreflightError, match="unsafe"):
        preflight.selected_env(link)


def test_snapshot_tree_is_stable_and_records_file_change(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    first = preflight.snapshot_tree(root)
    second = preflight.snapshot_tree(root)
    assert first == second
    assert first.entries == 1
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    changed = preflight.snapshot_tree(root)
    assert changed.digest != first.digest


def test_snapshot_tree_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    target = root / "a.txt"
    target.write_text("one\n", encoding="utf-8")
    (root / "alias.txt").symlink_to(target)
    with pytest.raises(preflight.PreflightError, match="symlink"):
        preflight.snapshot_tree(root)


def test_job_state_counts_active_and_locked_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    idle = jobs / "idle"
    idle.mkdir()
    (idle / "status.json").write_text('{"status":"done"}\n', encoding="utf-8")
    active = jobs / "active"
    active.mkdir()
    (active / "status.json").write_text('{"status":"running"}\n', encoding="utf-8")
    (active / ".lock").write_text("{}\n", encoding="utf-8")
    assert preflight.job_state(jobs) == {
        "job_count": 2,
        "active_job_count": 1,
        "locked_job_count": 1,
    }


def test_release_wrapper_contract_requires_protected_markers(tmp_path: Path) -> None:
    wrapper = tmp_path / "release.sh"
    wrapper.write_text(
        "\n".join(
            [
                "--expected-before",
                "--target-commit",
                "--confirm",
                '[[ "$CONFIRMATION" == "DEPLOY $TARGET_COMMIT" ]]',
                "image_holder_rendering_v0_2_live_acceptance=pass",
                "actual_book_readiness_claimed=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = preflight.check_release_wrapper(wrapper, "b" * 40)
    assert result["contract"] == "pass"
    assert len(result["sha256"]) == 64

    wrapper.write_text("--expected-before\n", encoding="utf-8")
    with pytest.raises(preflight.PreflightError, match="contract is incomplete"):
        preflight.check_release_wrapper(wrapper, "b" * 40)


def test_requirement_plan_is_read_only_for_current_repository() -> None:
    root = Path(__file__).resolve().parents[1]
    plan = preflight.load_requirement_plan(root, root / "requirements.txt")
    assert plan["policy"] == "unchanged"
    assert plan["additions"] == []
    assert plan["pillow_version"] == "12.3.0"


def test_preflight_source_does_not_contain_production_mutators() -> None:
    root = Path(__file__).resolve().parents[1]
    python_source = (root / "scripts" / "production_current_main_preflight.py").read_text(
        encoding="utf-8"
    )
    shell_source = (root / "scripts" / "production_current_main_preflight.sh").read_text(
        encoding="utf-8"
    )
    combined = python_source + "\n" + shell_source
    forbidden = (
        'systemctl", "start',
        'systemctl", "stop',
        'systemctl", "restart',
        '"git", "-C", str(repo_root), "fetch"',
        '"git", "-C", str(repo_root), "merge"',
        '"git", "-C", str(repo_root), "checkout"',
        '"git", "-C", str(repo_root), "reset"',
        '"pip", "install"',
    )
    for marker in forbidden:
        assert marker not in combined


def test_shell_wrapper_is_thin_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    shell = (root / "scripts" / "production_current_main_preflight.sh").read_text(
        encoding="utf-8"
    )
    assert "set -Eeuo pipefail" in shell
    assert "umask 077" in shell
    assert "production_current_main_preflight.py" in shell
    assert "exec /usr/bin/python3" in shell
