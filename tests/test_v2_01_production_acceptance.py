from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts import v2_01_live_acceptance as acceptance


PINNED_RUNTIME_PATH = (
    "/opt/book-system-runtime/pandoc/current/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


def test_read_env_value_does_not_execute_the_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    marker = tmp_path / "must-not-exist"
    env_file.write_text(
        "# protected settings\n"
        "BOOK_API_KEY='correct-key'\n"
        f"UNRELATED=$(touch {marker})\n",
        encoding="utf-8",
    )

    assert acceptance.read_env_value(env_file, "BOOK_API_KEY") == "correct-key"
    assert marker.exists() is False


def test_read_env_value_rejects_duplicate_or_empty_values(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    duplicate.write_text("BOOK_API_KEY=one\nBOOK_API_KEY=two\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly once"):
        acceptance.read_env_value(duplicate, "BOOK_API_KEY")

    empty = tmp_path / "empty"
    empty.write_text("BOOK_API_KEY=\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly once"):
        acceptance.read_env_value(empty, "BOOK_API_KEY")


def test_storage_manifest_detects_content_and_structure_changes(tmp_path: Path) -> None:
    books = tmp_path / "books"
    job = books / "jobs" / "job-1"
    job.mkdir(parents=True)
    status = job / "status.json"
    status.write_text('{"status":"done"}\n', encoding="utf-8")

    before = acceptance.storage_manifest(books)
    status.write_text('{"status":"failed"}\n', encoding="utf-8")
    after_content_change = acceptance.storage_manifest(books)
    assert after_content_change != before

    status.write_text('{"status":"done"}\n', encoding="utf-8")
    (job / ".lock").write_text("locked\n", encoding="utf-8")
    after_structure_change = acceptance.storage_manifest(books)
    assert after_structure_change != before


def test_http_acceptance_proves_authentication_and_both_results() -> None:
    correct_key = "production-key"
    calls: list[tuple[str, str, dict[str, object] | None, str | None]] = []

    def requester(url, method, payload, api_key):
        calls.append((url, method, payload, api_key))
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/ready"):
            return 200, {"ready": True}
        if url.endswith("/api/v1/status"):
            return 200, {"implemented": ["POST /api/v1/validate"]}
        if url.endswith("/api/v1/validate"):
            if api_key != correct_key:
                return 403, {"detail": "Forbidden"}
            if payload and payload.get("content") == "":
                return 200, {
                    "valid": False,
                    "errors": [{"code": "empty-manuscript"}],
                }
            return 200, {"valid": True, "errors": []}
        raise AssertionError(url)

    evidence = acceptance.run_http_acceptance(
        "https://publish.example",
        correct_key,
        requester=requester,
    )

    assert evidence["missing_key"] == 403
    assert evidence["wrong_key"] == 403
    assert evidence["valid"] is True
    assert evidence["invalid"] is False
    validation_calls = [call for call in calls if call[0].endswith("/validate")]
    assert len(validation_calls) == 4
    assert validation_calls[0][3] is None
    assert validation_calls[1][3] not in {None, correct_key}
    assert validation_calls[2][3] == correct_key
    assert validation_calls[3][3] == correct_key


def test_four_format_smoke_requires_real_file_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "templates").mkdir(parents=True)

    def fake_export(_source: Path, output_dir: Path, _log: Path) -> dict[str, str]:
        output_dir.mkdir(parents=True)
        (output_dir / "book-standard.pdf").write_bytes(b"%PDF-1.7\nstandard")
        (output_dir / "book-nd.pdf").write_bytes(b"%PDF-1.7\nnd")
        for name in ("book.epub", "book.docx"):
            with zipfile.ZipFile(output_dir / name, "w") as archive:
                archive.writestr("proof.txt", "valid")
        return {
            "pdf_standard": "book-standard.pdf",
            "pdf_nd": "book-nd.pdf",
            "epub": "book.epub",
            "docx": "book.docx",
        }

    monkeypatch.setattr(acceptance, "pandoc_export", fake_export)

    evidence = acceptance.run_four_format_smoke(repo_root)

    assert set(evidence) == {"pdf_standard", "pdf_nd", "epub", "docx"}
    assert all(item["size"] > 0 for item in evidence.values())
    assert all(len(item["sha256"]) == 64 for item in evidence.values())


def test_pinned_installer_uses_official_digest_verified_assets() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "scripts" / "install_pinned_pandoc.sh").read_text(
        encoding="utf-8"
    )

    assert 'PANDOC_VERSION="3.9.0.2"' in installer
    assert "a69abfababda8a56969a254b09f9553a7be89ddec00d4e0fe9fd585d71a67508" in installer
    assert "b6d21e8f9c3b15744f5a7ab40248019157ed7793875dbe0383d4c82ff572b528" in installer
    assert "github.com/jgm/pandoc/releases/download" in installer
    assert "--proto '=https'" in installer
    assert "sha256sum --check --strict --status" in installer
    assert "--sandbox" in installer
    assert "unsupported architecture" in installer


def test_every_installation_surface_uses_the_shared_pinned_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    install = (root / "scripts" / "install.sh").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    api_unit = (root / "deploy" / "systemd" / "book-system-api.service").read_text(
        encoding="utf-8"
    )
    worker_unit = (
        root / "deploy" / "systemd" / "book-system-worker.service"
    ).read_text(encoding="utf-8")

    assert "install_pinned_pandoc.sh" in install
    assert "apt-get install -y python3" in install
    assert "python3-pip pandoc" not in install
    assert "runuser -u www-data -- env PATH=" in install

    assert "Install exact export toolchain" in workflow
    assert "install_pinned_pandoc.sh" in workflow
    assert "apt-get install -y pandoc" not in workflow

    assert f"Environment=PATH={PINNED_RUNTIME_PATH}" in api_unit
    assert f"Environment=PATH={PINNED_RUNTIME_PATH}" in worker_unit


def test_production_launcher_is_exact_guarded_logged_and_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "production_v2_01_acceptance.sh").read_text(
        encoding="utf-8"
    )

    required_phrases = [
        "--execute",
        "origin/main is not the exact accepted commit",
        "running launcher is not the launcher stored in the exact accepted commit",
        "install_pinned_pandoc.sh",
        "check_runtime_compatibility.py",
        "runuser -u www-data -- env PATH=",
        "deploy_server.sh",
        "v2_01_live_acceptance.py",
        "retained-books-unchanged=pass",
        "v2-01-production-acceptance=pass",
        "/var/log/book-system",
    ]
    for phrase in required_phrases:
        assert phrase in launcher

    assert "merge_pull_request" not in launcher
    assert "git push" not in launcher
    assert "rm -rf -- \"$REPO_ROOT" not in launcher
