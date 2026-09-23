from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIRECTION = ROOT / "docs" / "PUBLICATION_COMPOSITION_DIRECTION_V0_1.md"
BASELINE = ROOT / "docs" / "PHASE_0_BASELINE_PRESERVATION.md"
GAP = ROOT / "docs" / "PHASE_0_GAP_MATRIX.md"
CURRENT = ROOT / "docs" / "CURRENT_PRODUCT_CONTRACT_V1.md"


def test_phase0_preserves_current_product_authority_and_exact_baseline() -> None:
    text = BASELINE.read_text(encoding="utf-8")
    assert "12a4d269e60048b4d42f8ab57c40916e8c7fd172" in text
    assert "CURRENT_PRODUCT_CONTRACT_V1.md" in text
    assert "fixed 12/12 current-engine denominator" in text
    assert "Phase 0 does not deploy anything" in text


def test_future_direction_makes_legacy_renderer_stack_transitional() -> None:
    text = DIRECTION.read_text(encoding="utf-8")
    assert "transitional current-engine dependencies only" in text
    assert "not part of the intended steady-state architecture" in text
    assert "fallback just in case" in text
    assert "Affinity document" in text


def test_gap_matrix_has_explicit_legacy_removal_rule() -> None:
    text = GAP.read_text(encoding="utf-8")
    assert "## Removal rule" in text
    assert "Pandoc/Lua/XeLaTeX" in text
    assert "not retained as a second permanent publishing architecture" in text


def test_current_product_contract_remains_current_engine_authority() -> None:
    text = CURRENT.read_text(encoding="utf-8")
    assert "Current Product Contract v1" in text
    assert "12/12" in text
    assert "pdf_standard" in text
    assert "pdf_nd" in text
    assert "epub" in text
    assert "docx" in text
