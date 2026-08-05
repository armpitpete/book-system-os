from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services.revision_package import (
    MANIFEST_NAME,
    README_NAME,
    RevisionPackageError,
    build_revision_package,
    verify_revision_package,
)
from app.services.revision_studio import (
    create_document,
    create_proposal,
    decide_proposal,
    get_current,
)


CURRENT = "# Chapter\n\nThe path crossed the field.\n"
PROPOSED = "# Chapter\n\nThe old path crossed the field.\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_SECURITY_CSRF_ENABLED", raising=False)
    return TestClient(app)


def revision_root(tmp_path: Path) -> Path:
    return tmp_path / "books" / "revisions"


def create_rejected_revision(tmp_path: Path, document_id: str = "chapter-07") -> str:
    root = revision_root(tmp_path)
    create_document(
        document_id=document_id,
        title="Chapter Seven",
        content=CURRENT,
        actor="Merrin",
        authority_ref="test:initial",
        root=root,
    )
    proposal = create_proposal(
        document_id=document_id,
        content=PROPOSED,
        rationale="Try a more specific sentence.",
        created_by="clarity-assistant",
        created_by_kind="assistant",
        evidence_refs=("reader:3",),
        validation_refs=("check:clarity",),
        root=root,
    )
    decide_proposal(
        document_id=document_id,
        proposal_id=proposal["proposal_id"],
        action="reject",
        actor="Merrin",
        authority_ref="test:reject",
        note="Keep the original cadence.",
        root=root,
    )
    return proposal["proposal_id"]


def archive_files(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content), mode="r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def build_zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_package_contains_current_proposals_decisions_history_and_readme(
    tmp_path: Path,
) -> None:
    proposal_id = create_rejected_revision(tmp_path)
    package = build_revision_package("chapter-07", root=revision_root(tmp_path))
    files = archive_files(package.content)

    assert README_NAME in files
    assert MANIFEST_NAME in files
    assert "revision/current.json" in files
    assert "revision/history.json" in files
    assert any(name.startswith("revision/versions/") for name in files)
    assert f"revision/proposals/{proposal_id}/proposal.json" in files
    assert f"revision/proposals/{proposal_id}/proposed.md" in files
    assert f"revision/proposals/{proposal_id}/decision.json" in files
    assert PROPOSED.encode("utf-8") == files[
        f"revision/proposals/{proposal_id}/proposed.md"
    ]
    assert b"Rejected and kept-for-later proposals remain" in files[README_NAME]

    current = json.loads(files["revision/current.json"])
    assert current["content_digest"] == get_current(
        "chapter-07", root=revision_root(tmp_path)
    )["content_digest"]
    decision = json.loads(files[f"revision/proposals/{proposal_id}/decision.json"])
    assert decision["action"] == "reject"
    history = json.loads(files["revision/history.json"])
    assert [event["event"] for event in history] == [
        "current_created",
        "proposal_created",
        "proposal_decided",
    ]


def test_unchanged_revision_state_exports_identical_bytes(tmp_path: Path) -> None:
    create_rejected_revision(tmp_path)
    first = build_revision_package("chapter-07", root=revision_root(tmp_path))
    second = build_revision_package("chapter-07", root=revision_root(tmp_path))
    assert first.content == second.content
    assert first.sha256 == second.sha256
    assert first.filename == "chapter-07-revision-package.zip"


def test_manifest_covers_every_payload_file_and_verifier_accepts_package(
    tmp_path: Path,
) -> None:
    create_rejected_revision(tmp_path)
    package = build_revision_package("chapter-07", root=revision_root(tmp_path))
    files = archive_files(package.content)
    manifest = json.loads(files[MANIFEST_NAME])

    recorded = {entry["path"] for entry in manifest["files"]}
    assert recorded == set(files) - {MANIFEST_NAME}
    verified = verify_revision_package(package.content)
    assert verified["valid"] is True
    assert verified["document_id"] == "chapter-07"
    assert verified["archive_sha256"] == package.sha256
    assert verified["verified_payload_files"] == len(files) - 1


def test_modified_payload_fails_manifest_verification(tmp_path: Path) -> None:
    proposal_id = create_rejected_revision(tmp_path)
    package = build_revision_package("chapter-07", root=revision_root(tmp_path))
    files = archive_files(package.content)
    files[f"revision/proposals/{proposal_id}/proposed.md"] = b"tampered\n"

    with pytest.raises(RevisionPackageError, match="failed verification") as error:
        verify_revision_package(build_zip(files))
    assert error.value.code == "package-digest-mismatch"


def test_missing_manifest_entry_and_unsafe_archive_path_fail_closed(
    tmp_path: Path,
) -> None:
    create_rejected_revision(tmp_path)
    package = build_revision_package("chapter-07", root=revision_root(tmp_path))
    files = archive_files(package.content)
    manifest = json.loads(files[MANIFEST_NAME])
    manifest["files"] = manifest["files"][:-1]
    files[MANIFEST_NAME] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with pytest.raises(RevisionPackageError, match="omits files") as missing:
        verify_revision_package(build_zip(files))
    assert missing.value.code == "manifest-file-mismatch"

    unsafe = build_zip({README_NAME: b"readme", MANIFEST_NAME: b"{}", "../escape": b"x"})
    with pytest.raises(RevisionPackageError, match="Unsafe package path") as traversal:
        verify_revision_package(unsafe)
    assert traversal.value.code == "unsafe-package-path"


def test_source_symlink_and_current_tampering_fail_before_export(tmp_path: Path) -> None:
    create_rejected_revision(tmp_path)
    root = revision_root(tmp_path)
    document_dir = root / "chapter-07"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = document_dir / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symbolic links are not supported in this test environment")
    with pytest.raises(RevisionPackageError, match="symbolic link") as symlink:
        build_revision_package("chapter-07", root=root)
    assert symlink.value.code == "revision-package-symlink"
    link.unlink()

    current = get_current("chapter-07", root=root)
    (document_dir / current["content_path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(RevisionPackageError, match="digest"):
        build_revision_package("chapter-07", root=root)


def test_dashboard_download_returns_deterministic_zip_and_history_link(
    client: TestClient,
    tmp_path: Path,
) -> None:
    create_rejected_revision(tmp_path)
    history = client.get("/revisions/chapter-07/history")
    assert history.status_code == 200
    assert "Download portable package" in history.text

    response = client.get("/revisions/chapter-07/package")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "chapter-07-revision-package.zip" in response.headers[
        "content-disposition"
    ]
    assert len(response.headers["x-content-sha256"]) == 64
    assert verify_revision_package(response.content)["valid"] is True


def test_authenticated_api_download_and_verify_round_trip(
    client: TestClient,
    tmp_path: Path,
) -> None:
    create_rejected_revision(tmp_path)
    download = client.get("/api/v1/revisions/documents/chapter-07/package")
    assert download.status_code == 200
    assert download.headers["x-revision-package-version"] == "0.1"

    verification = client.post(
        "/api/v1/revisions/package/verify",
        files={
            "package": (
                "chapter-07-revision-package.zip",
                download.content,
                "application/zip",
            )
        },
    )
    assert verification.status_code == 200, verification.text
    assert verification.json()["valid"] is True
    assert verification.json()["document_id"] == "chapter-07"


def test_status_reports_package_routes_as_implemented(client: TestClient) -> None:
    status = client.get("/api/v1/status")
    assert status.status_code == 200
    implemented = status.json()["implemented"]
    assert "GET /revisions/{document_id}/package" in implemented
    assert "GET /api/v1/revisions/documents/{document_id}/package" in implemented
    assert "POST /api/v1/revisions/package/verify" in implemented
