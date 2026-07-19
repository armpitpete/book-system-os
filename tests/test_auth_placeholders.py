from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


def test_example_placeholders_are_not_usable_production_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_API_KEY", "replace-with-a-long-random-secret")
    monkeypatch.setenv("BOOK_ADMIN_USERNAME", "replace-with-an-admin-name")
    monkeypatch.setenv("BOOK_ADMIN_PASSWORD", "replace-with-a-long-random-password")

    client = TestClient(app)
    assert client.get("/").status_code == 503
    assert client.post("/api/submit", json={"title": "A", "content": "# A"}).status_code == 503
