from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.ui import download_output
from app.version import APP_VERSION


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def job_directories(root: Path) -> list[Path]:
    jobs = root / "books" / "jobs"
    if not jobs.exists():
        return []
    return sorted(path for path in jobs.iterdir() if path.is_dir())


def read_job_status(job_dir: Path) -> dict:
    return json.loads((job_dir / "status.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    return TestClient(app)


def test_production_dashboard_fails_closed_without_credentials(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    response = client.get("/")
    assert response.status_code == 503
    assert response.json()["detail"] == "Dashboard authentication is not configured"


def test_production_api_fails_closed_without_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    response = client.post("/api/submit", json={"title": "A", "content": "# A"})
    assert response.status_code == 503
    assert response.json()["detail"] == "API authentication is not configured"


def test_local_mode_allows_explicit_unauthenticated_development(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    response = client.post("/api/submit", json={"title": "Local", "content": "# Local"})
    assert response.status_code == 200
    assert response.json()["state"] == "production"


def test_dashboard_basic_auth_accepts_only_configured_credentials(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("BOOK_ADMIN_PASSWORD", "correct-password")

    assert client.get("/").status_code == 401
    assert client.get("/", headers=basic_auth("operator", "wrong")).status_code == 401
    assert client.get("/", headers=basic_auth("operator", "correct-password")).status_code == 200


def test_incomplete_dashboard_credentials_fail_as_configuration_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_ADMIN_USERNAME", "operator")
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    response = client.get("/")
    assert response.status_code == 503
    assert response.json()["detail"] == "Dashboard authentication is incomplete"


def test_api_key_rejects_missing_and_wrong_keys(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_API_KEY", "correct-key")
    payload = {"title": "API", "content": "# API"}

    assert client.post("/api/submit", json=payload).status_code == 403
    assert client.post("/api/submit", json=payload, headers={"x-api-key": "wrong"}).status_code == 403
    response = client.post("/api/submit", json=payload, headers={"x-api-key": "correct-key"})
    assert response.status_code == 200
    assert response.json()["state"] == "production"


def test_dashboard_contains_job_type_selector_and_defaults_to_test(client: TestClient, tmp_path: Path) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert 'select name="state"' in page.text
    assert '<option value="test" selected>' in page.text

    response = client.post(
        "/submit-form",
        data={"title": "Manual test", "content": "# Manual test"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    jobs = job_directories(tmp_path)
    assert len(jobs) == 1
    assert read_job_status(jobs[0])["state"] == "test"


def test_dashboard_can_explicitly_create_production_job(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/submit-form",
        data={"title": "Production", "content": "# Production", "state": "production"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    jobs = job_directories(tmp_path)
    assert len(jobs) == 1
    assert read_job_status(jobs[0])["state"] == "production"


def test_dashboard_rejects_invalid_job_type(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/submit-form",
        data={"title": "Bad", "content": "# Bad", "state": "archived"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert job_directories(tmp_path) == []


def test_api_submission_is_always_production(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/submit", json={"title": "API", "content": "# API"})
    assert response.status_code == 200
    jobs = job_directories(tmp_path)
    assert len(jobs) == 1
    assert read_job_status(jobs[0])["state"] == "production"


def test_status_and_dashboard_use_one_version(client: TestClient) -> None:
    status_response = client.get("/api/v1/status")
    dashboard_response = client.get("/")
    assert status_response.status_code == 200
    assert status_response.json()["version"] == APP_VERSION
    assert f"Book System OS v{APP_VERSION}" in dashboard_response.text


def test_download_rejects_path_traversal(
    client: TestClient,
    tmp_path: Path,
) -> None:
    client.post(
        "/submit-form",
        data={"title": "Download", "content": "# Download"},
        follow_redirects=False,
    )
    job_id = job_directories(tmp_path)[0].name
    with pytest.raises(HTTPException) as exc_info:
        download_output(job_id, "../secret.txt")
    assert exc_info.value.status_code == 400
