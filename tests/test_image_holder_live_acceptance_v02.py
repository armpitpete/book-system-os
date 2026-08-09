from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from scripts.image_holder_live_acceptance import check_image_holder_runtime


REPO_ROOT = Path(__file__).resolve().parents[1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for image-holder live acceptance")


@pytest.mark.integration
def test_image_holder_live_acceptance_exercises_v02_four_format_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_export_toolchain()
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(REPO_ROOT))

    checks = check_image_holder_runtime(REPO_ROOT)

    assert checks["pillow_version"] == "12.3.0"
    assert checks["representative_holder"] == "pass"
    assert checks["low_resolution_fail_closed"] == "pass"
    assert checks["remote_holder_fail_closed"] == "pass"
    assert checks["four_format_rendering"] == "pass"
    assert checks["pdf_standard"] == "pass"
    assert checks["pdf_nd"] == "pass"
    assert checks["docx_structure"] == "pass"
    assert checks["epub_structure"] == "pass"
    assert checks["relative_input_resource_resolution"] == "pass"
    assert checks["author_positioning_sanitised"] == "pass"
    assert SHA256_RE.fullmatch(checks["renderer_sha256"])
    assert SHA256_RE.fullmatch(checks["build_log_sha256"])

    outputs = checks["outputs"]
    assert set(outputs) == {"pdf_standard", "pdf_nd", "epub", "docx"}
    for record in outputs.values():
        assert record["bytes"] > 0
        assert SHA256_RE.fullmatch(record["sha256"])


def test_protected_wrapper_records_v02_live_acceptance_marker() -> None:
    wrapper = (REPO_ROOT / "scripts" / "production_current_main_release.sh").read_text(
        encoding="utf-8"
    )

    assert 'env BOOK_SYSTEM_ROOT="$REPO_ROOT" \\' in wrapper
    assert "image_holder_rendering_v0_2_live_acceptance=pass" in wrapper
    assert "Image-holder rendering v0.2 live acceptance: pass" in wrapper
