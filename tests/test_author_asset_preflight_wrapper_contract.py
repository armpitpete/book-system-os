from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "scripts" / "production_current_main_preflight.sh"


def test_late_author_asset_failure_overrides_base_pass_evidence() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert 'cp -- "$evidence_dir/result.txt" "$evidence_dir/base-result.txt"' in source
    assert 'echo "FAIL"' in source
    assert 'echo "author-asset preflight invariant failed"' in source
    assert 'echo "deployment-authorized=false"' in source
    assert '>"$evidence_dir/result.txt"' in source
    assert 'exit "$asset_status"' in source


def test_base_pass_output_is_emitted_only_after_asset_after_check() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    after_check = source.index("--phase after")
    failure_branch = source.index('if [[ "$asset_status" -ne 0 ]]')
    final_base_output = source.rindex('cat "$BASE_OUT"')
    assert after_check < failure_branch < final_base_output
