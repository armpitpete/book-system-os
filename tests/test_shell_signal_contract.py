from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "script_name",
    ["install_pinned_pandoc.sh", "production_v2_01_acceptance.sh"],
)
def test_production_shell_scripts_exit_on_termination_signals(
    script_name: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / script_name).read_text(encoding="utf-8")

    assert "trap cleanup EXIT" in script
    assert "trap 'exit 129' HUP" in script
    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script
    assert "trap cleanup EXIT HUP INT TERM" not in script
