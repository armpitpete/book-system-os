from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services import manuscript_validation


def job_directories(root: Path) -> list[Path]:
    jobs = root / "books" / "jobs"
    if not jobs.exists():
        return []
    return sorted(path for path in jobs.iterdir() if path.is_dir())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BOOK_MAX_MANUSCRIPT_BYTES", raising=False)
    return TestClient(app)


def representative_ast() -> dict[str, object]:
    return {
        "pandoc-api-version": [1, 23, 1],
        "meta": {
            "title": {
                "t": "MetaInlines",
                "c": [{"t": "Str", "c": "Validated"}],
            },
            "lang": {"t": "MetaString", "c": "en-GB"},
        },
        "blocks": [
            {
                "t": "Header",
                "c": [1, ["opening", [], []], [{"t": "Str", "c": "Opening"}]],
            },
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Image",
                        "c": [
                            ["", [], []],
                            [{"t": "Str", "c": "Image"}],
                            ["image.png", ""],
                        ],
                    },
                    {"t": "Space"},
                    {
                        "t": "Note",
                        "c": [
                            {
                                "t": "Para",
                                "c": [{"t": "Str", "c": "Footnote"}],
                            }
                        ],
                    },
                ],
            },
            {
                "t": "Header",
                "c": [3, ["jump", [], []], [{"t": "Str", "c": "Jump"}]],
            },
            {"t": "BulletList", "c": []},
            {"t": "Table", "c": []},
            {"t": "RawBlock", "c": ["html", "<div>probe</div>"]},
        ],
    }


def install_successful_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    document = representative_ast()
    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (document, False),
    )


def test_validation_service_is_deterministic_and_reports_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_successful_parser(monkeypatch)
    markdown = "---\r\ntitle: Validated\r\nlang: en-GB\r\n---\r\n\r\n# Opening  \r\n\r\n### Jump\r\n"

    first = manuscript_validation.validate_manuscript(
        title="Validated",
        markdown=markdown,
    )
    second = manuscript_validation.validate_manuscript(
        title="Validated",
        markdown=markdown,
    )

    assert first == second
    assert first["valid"] is True
    assert first["errors"] == []
    warning_codes = {finding["code"] for finding in first["warnings"]}
    assert "heading-level-jump" in warning_codes
    assert "raw-format-content" in warning_codes
    summary = first["summary"]
    assert summary["heading_count"] == 2
    assert summary["level_one_heading_count"] == 1
    assert summary["maximum_heading_level"] == 3
    assert summary["image_count"] == 1
    assert summary["table_count"] == 1
    assert summary["footnote_count"] == 1
    assert summary["list_count"] == 1
    assert summary["raw_content_count"] == 1
    assert summary["normalisation_changed"] is True
    assert first["contract_version"] == "0.2"


def test_empty_manuscript_is_invalid_without_starting_pandoc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(_markdown: str) -> tuple[dict[str, object], bool]:
        raise AssertionError("Pandoc must not run for an empty manuscript")

    monkeypatch.setattr(manuscript_validation, "_parse_with_pandoc", fail_if_called)

    result = manuscript_validation.validate_manuscript(
        title="Empty",
        markdown=" \r\n\t",
    )

    assert result["valid"] is False
    assert [finding["code"] for finding in result["errors"]] == ["empty-manuscript"]
    assert result["summary"]["block_count"] == 0


def test_pandoc_parse_failure_is_a_validation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (None, False),
    )

    result = manuscript_validation.validate_manuscript(
        title="Malformed",
        markdown='---\ntitle: "left open\n---\n\n# Body\n',
    )

    assert result["valid"] is False
    assert [finding["code"] for finding in result["errors"]] == [
        "manuscript-parse-error"
    ]
    assert result["warnings"] == []


def test_pandoc_unavailable_is_a_controlled_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_pandoc(
        *_args: object,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("pandoc")

    monkeypatch.setattr(manuscript_validation.subprocess, "run", missing_pandoc)

    with pytest.raises(manuscript_validation.ValidationServiceError) as exc_info:
        manuscript_validation.validate_manuscript(
            title="Unavailable",
            markdown="# Manuscript\n",
        )

    assert exc_info.value.code == "validation-tool-unavailable"
    assert exc_info.value.payload() == {
        "detail": "Pandoc is unavailable for manuscript validation",
        "code": "validation-tool-unavailable",
    }


def test_validation_endpoint_returns_controlled_service_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unavailable(_markdown: str) -> tuple[dict[str, object] | None, bool]:
        raise manuscript_validation.ValidationServiceError(
            "Pandoc is unavailable for manuscript validation",
            code="validation-tool-unavailable",
        )

    monkeypatch.setattr(manuscript_validation, "_parse_with_pandoc", unavailable)

    response = client.post(
        "/api/v1/validate",
        json={"title": "Unavailable", "content": "# Manuscript\n"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Pandoc is unavailable for manuscript validation",
        "code": "validation-tool-unavailable",
    }
    assert job_directories(tmp_path) == []


def test_validation_endpoint_creates_no_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)

    response = client.post(
        "/api/v1/validate",
        json={"title": "Read only", "content": "# Read only\n"},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert job_directories(tmp_path) == []


def test_invalid_manuscript_returns_http_200_without_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (None, False),
    )

    response = client.post(
        "/api/v1/validate",
        json={"title": "Malformed", "content": "---\ntitle: \"open\n---\n"},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["errors"][0]["code"] == "manuscript-parse-error"
    assert job_directories(tmp_path) == []


def test_validation_endpoint_requires_api_key_in_production(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_successful_parser(monkeypatch)
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_API_KEY", "validation-key")
    payload = {"title": "Protected", "content": "# Protected\n"}

    assert client.post("/api/v1/validate", json=payload).status_code == 403
    response = client.post(
        "/api/v1/validate",
        json=payload,
        headers={"x-api-key": "validation-key"},
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_validation_endpoint_reuses_manuscript_size_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)
    monkeypatch.setenv("BOOK_MAX_MANUSCRIPT_BYTES", "4")

    response = client.post(
        "/api/v1/validate",
        json={"title": "Too large", "content": "12345"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "manuscript-too-large"
    assert response.json()["limit"] == 4
    assert response.json()["actual"] == 5
    assert job_directories(tmp_path) == []


def test_validation_endpoint_rejects_malformed_request_without_job(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.post("/api/v1/validate", json={"title": "Missing content"})

    assert response.status_code == 422
    assert job_directories(tmp_path) == []


def test_status_reports_only_validation_as_newly_implemented(client: TestClient) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    payload = response.json()
    assert "POST /api/v1/validate" in payload["implemented"]
    assert "POST /api/v1/validate" not in payload["not_yet_implemented"]
    assert "POST /api/v1/publish" in payload["not_yet_implemented"]
