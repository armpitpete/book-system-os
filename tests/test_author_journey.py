from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    return TestClient(app)


def job_directories(root: Path) -> list[Path]:
    jobs = root / "books" / "jobs"
    if not jobs.exists():
        return []
    return sorted(path for path in jobs.iterdir() if path.is_dir())


def dry_run_result(*, publishable: bool) -> dict:
    errors = [] if publishable else [
        {
            "code": "invalid-structure",
            "severity": "error",
            "message": "Representative structural problem.",
        }
    ]
    return {
        "publishable": publishable,
        "validation": {
            "valid": publishable,
            "errors": errors,
            "warnings": [
                {
                    "code": "representative-warning",
                    "severity": "warning",
                    "message": "Representative warning.",
                }
            ],
            "summary": {
                "heading_count": 3,
                "image_count": 1,
                "table_count": 2,
                "footnote_count": 4,
                "broken_internal_link_count": 0,
            },
        },
        "outputs": [
            {"filename": "book-standard.pdf"},
            {"filename": "book-nd.pdf"},
            {"filename": "book.epub"},
            {"filename": "book.docx"},
        ],
        "source_bytes": 123,
        "rendering_attempted": False,
        "job_created": False,
    }


def test_dashboard_exposes_one_author_journey(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "1. Prepare" in response.text
    assert "2. Check" in response.text
    assert "3. Build" in response.text
    assert "4. Review" in response.text
    assert 'href="/assets"' in response.text
    assert 'href="/revisions"' in response.text
    assert 'action="/check-form"' in response.text
    assert "Check book" in response.text
    assert "A Book for Neurodivergent Minds" not in response.text


def test_successful_book_check_is_side_effect_free_and_offers_builds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.api.ui.build_publish_dry_run",
        lambda **_kwargs: dry_run_result(publishable=True),
    )

    response = client.post(
        "/check-form",
        data={
            "title": "Real Book",
            "language": "en-GB",
            "content": "# Real Book\n\nText.",
        },
    )

    assert response.status_code == 200
    assert "Book check passed" in response.text
    assert "No job or artifact was created" in response.text
    assert "book-standard.pdf" in response.text
    assert "book-nd.pdf" in response.text
    assert "book.epub" in response.text
    assert "book.docx" in response.text
    assert "Queue test build" in response.text
    assert "Queue real book build" in response.text
    assert 'name="language" value="en-GB"' in response.text
    assert job_directories(tmp_path) == []


def test_failed_book_check_does_not_offer_queue_actions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "app.api.ui.build_publish_dry_run",
        lambda **_kwargs: dry_run_result(publishable=False),
    )

    response = client.post(
        "/check-form",
        data={"title": "Broken", "content": "# Broken"},
    )

    assert response.status_code == 200
    assert "Book check needs attention" in response.text
    assert "invalid-structure" in response.text
    assert "Queue test build" not in response.text
    assert "Queue real book build" not in response.text
    assert job_directories(tmp_path) == []


def test_book_check_rejects_blank_markdown_without_creating_job(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.post(
        "/check-form",
        data={"title": "Blank", "content": "   "},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Markdown content is required"
    assert job_directories(tmp_path) == []
