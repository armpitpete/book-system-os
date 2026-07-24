from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.version import git_commit_label


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    return TestClient(app)


def test_commit_label_reads_loose_head_ref_without_git_process(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    branch_ref = git_dir / "refs" / "heads" / "main"
    branch_ref.parent.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    branch_ref.write_text(
        "86e0227734686c94c186a2a453cbb0fcd65cbb50\n",
        encoding="utf-8",
    )

    assert git_commit_label(tmp_path) == "86e0227"


def test_commit_label_reads_packed_ref(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        "86e0227734686c94c186a2a453cbb0fcd65cbb50 refs/heads/main\n",
        encoding="utf-8",
    )

    assert git_commit_label(tmp_path) == "86e0227"


def test_commit_label_fails_closed_for_missing_or_invalid_metadata(tmp_path: Path) -> None:
    assert git_commit_label(tmp_path) == "unknown"

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("not-a-commit\n", encoding="utf-8")
    assert git_commit_label(tmp_path) == "unknown"


def test_dashboard_marks_markdown_as_required(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<textarea name="content" required' in response.text


def test_dashboard_rejects_blank_markdown_without_creating_job(
    client: TestClient,
    tmp_path: Path,
) -> None:
    response = client.post(
        "/submit-form",
        data={"title": "Blank", "content": "   ", "state": "test"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Markdown content is required"
    jobs_root = tmp_path / "books" / "jobs"
    assert not jobs_root.exists() or list(jobs_root.iterdir()) == []
