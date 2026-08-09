from __future__ import annotations

from pathlib import Path

from scripts import production_author_asset_preflight as asset_preflight


REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "scripts" / "author_asset_live_acceptance.py"
RELEASE = REPO / "scripts" / "production_current_main_release.sh"


def test_live_acceptance_is_read_only_and_checks_auth_route_contract() -> None:
    source = LIVE.read_text(encoding="utf-8")
    for required in (
        "author-asset-workspace-live-acceptance-v0.1",
        '"author-assets" not in enabled',
        'GET /assets',
        'POST /assets',
        'GET /assets/{asset_id}',
        'POST /assets/{asset_id}/configure',
        'GET /assets/{asset_id}/preview',
        "expected 401",
        "Basic authentication",
        "Author Asset Workspace",
        "Upload image",
        "not a freeform DTP canvas",
        "Author asset unavailable",
        "repository-remained-clean",
        "actual_book_readiness_claimed",
    ):
        assert required in source

    for forbidden in (
        "store_author_asset(",
        "create_job(",
        "shutil.rmtree",
        "unlink(",
        'method="POST"',
        "git reset",
        "git clean",
        "git checkout",
        "systemctl restart",
    ):
        assert forbidden not in source


def test_release_wrapper_requires_and_runs_author_asset_live_acceptance() -> None:
    source = RELEASE.read_text(encoding="utf-8")
    for required in (
        "AUTHOR_ASSET_ACCEPTANCE",
        "author_asset_live_acceptance.py",
        "Author Asset Workspace live acceptance failed",
        "author_asset_workspace_v0_1_live_acceptance=pass",
        "Author Asset Workspace v0.1 live acceptance: pass",
    ):
        assert required in source


def test_asset_preflight_binds_to_release_acceptance_contract() -> None:
    result = asset_preflight.check_release_contract(REPO)
    assert result["contract"] == "pass"
    assert len(result["release_wrapper_sha256"]) == 64
    assert len(result["live_acceptance_sha256"]) == 64
