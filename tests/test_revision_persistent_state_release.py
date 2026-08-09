from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services.revision_studio import create_document


REPO = Path(__file__).resolve().parents[1]
BACKUP = REPO / "scripts" / "backup_persistent_state.sh"
VALIDATE = REPO / "scripts" / "validate_backup.py"
RELEASE = REPO / "scripts" / "production_current_main_release.sh"
LIVE = REPO / "scripts" / "current_main_live_acceptance.py"


def _root(tmp_path: Path, *, secret: str = "release-secret-value") -> Path:
    root = tmp_path / "book-system"
    (root / "books" / "jobs").mkdir(parents=True)
    (root / "books" / "revisions").mkdir(parents=True)
    (root / "books" / "assets").mkdir(parents=True)
    (root / "logs").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "config" / "env").write_text(
        "BOOK_SYSTEM_ENV=test\n"
        "BOOK_BIND_PORT=8088\n"
        f"BOOK_API_KEY={secret}\n",
        encoding="utf-8",
    )
    return root


def test_persistent_stores_are_ignored_but_anchors_are_tracked() -> None:
    for relative in (
        "books/revisions/probe/current.json",
        "books/assets/0123456789abcdef0123456789abcdef/source.png",
    ):
        ignored = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", relative],
            check=False,
        )
        assert ignored.returncode == 0

    for relative in ("books/revisions/.gitkeep", "books/assets/.gitkeep"):
        anchor = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", relative],
            check=False,
        )
        assert anchor.returncode == 1
        assert (REPO / relative).is_file()


def test_persistent_backup_round_trip_includes_revision_studio_and_author_assets(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    revisions = root / "books" / "revisions"
    created = create_document(
        document_id="chapter-07",
        title="Chapter Seven",
        content="# Chapter Seven\n\nRetained manuscript.\n",
        actor="Merrin",
        authority_ref="test:accepted",
        root=revisions,
    )

    asset = root / "books" / "assets" / "0123456789abcdef0123456789abcdef"
    asset.mkdir()
    (asset / "source.png").write_bytes(b"author-image-bytes")
    (asset / "metadata.json").write_text(
        json.dumps(
            {
                "asset_id": "0123456789abcdef0123456789abcdef",
                "stored_filename": "source.png",
                "sha256": "fixture",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    archive = tmp_path / "persistent.tar.gz"
    completed = subprocess.run(
        ["bash", str(BACKUP), "--root", str(root), str(archive)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "persistent-backup=pass" in completed.stdout
    assert "persistent-backup-revision-restore=pass" in completed.stdout
    assert "persistent-backup-author-assets-restore=pass" in completed.stdout

    restored = tmp_path / "restored"
    verified = subprocess.run(
        ["python", str(VALIDATE), str(archive), "--restore-root", str(restored)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    restored_current = json.loads(
        (restored / "books" / "revisions" / "chapter-07" / "current.json").read_text(
            encoding="utf-8"
        )
    )
    assert restored_current["content_digest"] == created["content_digest"]
    restored_markdown = (
        restored
        / "books"
        / "revisions"
        / "chapter-07"
        / created["content_path"]
    ).read_text(encoding="utf-8")
    assert restored_markdown == "# Chapter Seven\n\nRetained manuscript.\n"
    assert (
        restored
        / "books"
        / "assets"
        / "0123456789abcdef0123456789abcdef"
        / "source.png"
    ).read_bytes() == b"author-image-bytes"

    metadata_extract = tmp_path / "metadata"
    metadata_extract.mkdir()
    subprocess.run(
        [
            "tar",
            "-xzf",
            str(archive),
            "-C",
            str(metadata_extract),
            "book-system-backup/backup-metadata.json",
        ],
        check=True,
        timeout=30,
    )
    metadata = json.loads(
        (metadata_extract / "book-system-backup" / "backup-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert "books/revisions" in metadata["included"]
    assert "books/assets" in metadata["included"]
    assert metadata["persistent_state_extension"] == 2


def test_persistent_backup_rejects_configured_secret_in_revision_state(
    tmp_path: Path,
) -> None:
    secret = "do-not-copy-this-secret"
    root = _root(tmp_path, secret=secret)
    revisions = root / "books" / "revisions"
    create_document(
        document_id="secret-test",
        title="Secret test",
        content=f"# Secret\n\n{secret}\n",
        actor="Merrin",
        authority_ref="test:secret",
        root=revisions,
    )
    archive = tmp_path / "must-not-exist.tar.gz"
    completed = subprocess.run(
        ["bash", str(BACKUP), "--root", str(root), str(archive)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode != 0
    assert "configured secret value" in completed.stderr
    assert not archive.exists()


def test_current_main_release_is_additive_fail_closed_wrapper() -> None:
    source = RELEASE.read_text(encoding="utf-8")
    for required in (
        "production_corpus_runtime_release_configured.sh",
        "backup_persistent_state.sh",
        "current_main_live_acceptance.py",
        "revisions-before.json",
        "revisions-after.json",
        "predeploy-persistent-state.tar.gz",
        "CURRENT MAIN RELEASE — PASS",
        "actual_book_readiness_claimed=false",
    ):
        assert required in source
    assert "cmp -s" in source
    assert "merge-base --is-ancestor" in source
    assert "origin/main" in source
    for forbidden in ("git reset", "git clean", "git checkout"):
        assert forbidden not in source


def test_live_acceptance_is_non_mutating_and_fail_closed() -> None:
    source = LIVE.read_text(encoding="utf-8")
    for required in (
        "GET /revisions",
        "not-found",
        "BOS-RDY-001",
        "unevaluated_readiness_report",
        "actual_book_readiness_claimed",
        "repository-remained-clean",
    ):
        assert required in source
    assert "api_create_revision" not in source
    assert "create_document(" not in source
    assert "create_proposal(" not in source
    assert "decide_proposal(" not in source
