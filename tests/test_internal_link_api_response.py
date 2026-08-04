from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services.security import reset_security_state


@pytest.mark.integration
def test_authenticated_validation_exposes_internal_link_counts_without_job_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for the public validation response test")

    api_key = "internal-link-endpoint-test-key"
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "test")
    monkeypatch.setenv("BOOK_API_KEY", api_key)
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    reset_security_state()

    jobs = tmp_path / "books" / "jobs"
    manuscript = (
        "---\n"
        "title: Internal link endpoint\n"
        "lang: en-GB\n"
        "---\n\n"
        "# Opening {#opening}\n\n"
        "[Valid](#opening)\n\n"
        "[Broken first](#missing-section)\n\n"
        "[Broken repeated](#missing-section)\n"
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/validate",
            headers={"X-API-Key": api_key},
            json={"title": "Internal link endpoint", "content": manuscript},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert payload["contract_version"] == "0.2"
    assert payload["summary"]["internal_link_count"] == 3
    assert payload["summary"]["broken_internal_link_count"] == 2
    assert [
        finding
        for finding in payload["warnings"]
        if finding["code"] == "broken-internal-link"
    ] == [
        {
            "code": "broken-internal-link",
            "severity": "warning",
            "message": "Internal link target was not found: #missing-section",
            "location": None,
        }
    ]
    assert jobs.exists() is False

    reset_security_state()
