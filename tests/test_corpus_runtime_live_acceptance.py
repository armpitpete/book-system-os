from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import corpus_runtime_live_acceptance as acceptance


def test_internal_link_response_contract() -> None:
    evidence = acceptance.assert_internal_link_response(
        {
            "valid": True,
            "errors": [],
            "warnings": [
                {
                    "code": "broken-internal-link",
                    "severity": "warning",
                    "message": "Internal link target was not found: #missing-section",
                    "location": None,
                }
            ],
            "summary": {
                "internal_link_count": 3,
                "broken_internal_link_count": 2,
            },
            "contract_version": "0.2",
        }
    )

    assert evidence == {
        "valid": True,
        "internal_link_count": 3,
        "broken_internal_link_count": 2,
        "broken_warning_count": 1,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        {"valid": False},
        {"summary": {"internal_link_count": 2, "broken_internal_link_count": 2}},
        {"summary": {"internal_link_count": 3, "broken_internal_link_count": 1}},
        {"warnings": []},
    ],
)
def test_internal_link_response_rejects_wrong_public_contract(
    mutation: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "valid": True,
        "errors": [],
        "warnings": [
            {
                "code": "broken-internal-link",
                "severity": "warning",
                "message": "Internal link target was not found: #missing-section",
                "location": None,
            }
        ],
        "summary": {
            "internal_link_count": 3,
            "broken_internal_link_count": 2,
        },
        "contract_version": "0.2",
    }
    payload.update(mutation)

    with pytest.raises(RuntimeError):
        acceptance.assert_internal_link_response(payload)


def test_storage_manifest_detects_content_and_preserves_no_secrets(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    nested = root / "job-1"
    nested.mkdir(parents=True)
    source = nested / "status.json"
    source.write_text(json.dumps({"status": "done"}) + "\n", encoding="utf-8")

    first = acceptance.storage_manifest(root)
    second = acceptance.storage_manifest(root)
    assert first == second
    assert any(entry.get("path") == "job-1/status.json" for entry in first)
    assert "done" not in json.dumps(first)

    source.write_text(json.dumps({"status": "failed"}) + "\n", encoding="utf-8")
    assert acceptance.storage_manifest(root) != first


@pytest.mark.integration
def test_private_pipeline_acceptance_proves_runtime_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = [tool for tool in ("pandoc", "xelatex", "mutool") if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"required live-acceptance tools are unavailable: {', '.join(missing)}")

    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(repository_root))
    evidence_dir = tmp_path / "evidence"

    result = acceptance.run_pipeline_acceptance(
        repo_root=repository_root,
        evidence_dir=evidence_dir,
    )

    assert result["missing_image"] == {
        "result": 1,
        "status": "failed",
        "step": "input-validation",
        "failure_code": "missing-image-file",
        "outputs": 0,
        "manifest_created": False,
        "export_started": False,
    }
    assert result["greek_cyrillic"]["result"] == 0
    assert result["greek_cyrillic"]["output_evidence_count"] == 4
    assert result["greek_cyrillic"]["build_log_clean"] is True
    assert (evidence_dir / "missing-image" / "status.json").is_file()
    assert (evidence_dir / "greek-cyrillic" / "book-standard.pdf").is_file()
    assert (evidence_dir / "greek-cyrillic" / "book-nd.pdf").is_file()
    assert (evidence_dir / "greek-cyrillic" / "book.epub").is_file()
    assert (evidence_dir / "greek-cyrillic" / "book.docx").is_file()
