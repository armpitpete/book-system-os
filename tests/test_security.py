from __future__ import annotations

import json
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services import security as security_module
from app.services.job_queue import (
    create_job,
    read_job_events,
    read_status,
    write_status,
)
from app.services.security import reset_security_state, security_audit_path

CSRF_RE = re.compile(r'name="csrf_token" value="([A-Za-z0-9_-]+)"')
PRIVATE_PASSWORD = "H06-private-admin-password"
PRIVATE_API_KEY = "H06-private-api-key"
PRIVATE_MARKDOWN = "H06-PRIVATE-MANUSCRIPT-CONTENT"
PRIVATE_TITLE = "H06 Private Book Title"


@pytest.fixture
def secure_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "test")
    monkeypatch.setenv("BOOK_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("BOOK_ADMIN_PASSWORD", PRIVATE_PASSWORD)
    monkeypatch.setenv("BOOK_API_KEY", PRIVATE_API_KEY)
    monkeypatch.setenv("BOOK_SECURITY_CSRF_ENABLED", "true")
    monkeypatch.setenv("BOOK_SECURITY_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("BOOK_SECURITY_AUDIT_ENABLED", "true")
    monkeypatch.setenv("BOOK_SECURITY_REQUEST_LIMIT", "1000")
    monkeypatch.setenv("BOOK_SECURITY_REQUEST_WINDOW_SECONDS", "60")
    monkeypatch.setenv("BOOK_SECURITY_AUTH_FAILURE_LIMIT", "5")
    monkeypatch.setenv("BOOK_SECURITY_AUTH_FAILURE_WINDOW_SECONDS", "300")
    monkeypatch.setenv("BOOK_SECURITY_CSRF_COOKIE_SECONDS", "3600")
    monkeypatch.setenv("BOOK_SECURITY_RATE_LIMIT_MAX_KEYS", "128")
    monkeypatch.setenv("BOOK_MAX_REQUEST_BYTES", "6291456")
    monkeypatch.setenv("BOOK_MAX_MANUSCRIPT_BYTES", "5242880")
    monkeypatch.setenv("BOOK_MAX_ACTIVE_JOBS", "20")
    monkeypatch.setenv("BOOK_MAX_JOB_BYTES", "209715200")
    monkeypatch.setenv("BOOK_MAX_TOTAL_STORAGE_BYTES", "10737418240")

    (tmp_path / "books" / "jobs").mkdir(parents=True)
    (tmp_path / "logs").mkdir(parents=True)
    reset_security_state()
    yield tmp_path
    reset_security_state()


def basic_auth(password: str = PRIVATE_PASSWORD) -> tuple[str, str]:
    return ("operator", password)


def dashboard_token(client: TestClient) -> str:
    response = client.get("/", auth=basic_auth())
    assert response.status_code == 200, response.text
    match = CSRF_RE.search(response.text)
    assert match, response.text
    token = match.group(1)
    assert client.cookies.get("book_csrf") == token
    return token


def audit_events() -> list[dict]:
    path = security_audit_path()
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_dashboard_forms_receive_csrf_and_submission_is_audited(
    secure_root: Path,
) -> None:
    with TestClient(app) as client:
        response = client.get("/", auth=basic_auth())
        assert response.status_code == 200
        tokens = CSRF_RE.findall(response.text)
        assert len(tokens) >= 2
        assert len(set(tokens)) == 1
        token = tokens[0]
        assert client.cookies.get("book_csrf") == token

        submitted = client.post(
            "/submit-form",
            auth=basic_auth(),
            data={
                "title": PRIVATE_TITLE,
                "content": PRIVATE_MARKDOWN,
                "state": "test",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

    assert submitted.status_code == 303, submitted.text
    jobs = sorted((secure_root / "books" / "jobs").iterdir())
    assert len(jobs) == 1
    assert read_status(jobs[0])["state"] == "test"

    events = audit_events()
    submit = [event for event in events if event["event"] == "admin.job.submit"]
    assert len(submit) == 1
    assert submit[0]["outcome"] == "authorised"
    assert submit[0]["details"] == {"state": "test"}

    audit_text = security_audit_path().read_text(encoding="utf-8")
    assert stat.S_IMODE(security_audit_path().stat().st_mode) == 0o600
    for private in (
        PRIVATE_PASSWORD,
        PRIVATE_API_KEY,
        PRIVATE_TITLE,
        PRIVATE_MARKDOWN,
        token,
    ):
        assert private not in audit_text


def test_missing_invalid_and_cross_site_csrf_are_refused_without_jobs(
    secure_root: Path,
) -> None:
    with TestClient(app) as client:
        token = dashboard_token(client)
        base = {
            "title": "Refused",
            "content": "# Refused",
            "state": "test",
        }

        missing = client.post(
            "/submit-form",
            auth=basic_auth(),
            data=base,
            follow_redirects=False,
        )
        invalid = client.post(
            "/submit-form",
            auth=basic_auth(),
            data={**base, "csrf_token": "invalid"},
            follow_redirects=False,
        )
        cross_site = client.post(
            "/submit-form",
            auth=basic_auth(),
            headers={"Origin": "https://attacker.invalid"},
            data={**base, "csrf_token": token},
            follow_redirects=False,
        )

    assert missing.status_code == 403
    assert invalid.status_code == 403
    assert cross_site.status_code == 403
    assert list((secure_root / "books" / "jobs").iterdir()) == []

    failures = [
        event["details"]["reason_code"]
        for event in audit_events()
        if event["event"] == "csrf.failure"
    ]
    assert failures == ["missing-token", "invalid-token", "cross-site"]


def test_lifecycle_retry_and_cleanup_actions_are_audited(
    secure_root: Path,
) -> None:
    _, failed = create_job(
        title="Failed fixture",
        markdown="# Failed",
        state="test",
    )
    write_status(
        failed,
        status="failed",
        step="fixture",
        message="Fixture failure",
    )

    _, old = create_job(
        title="Old fixture",
        markdown="# Old",
        state="test",
    )
    write_status(old, status="done", step="complete", message="Done")
    metadata_path = old / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["created_at"] = "2020-01-01T00:00:00+00:00"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        token = dashboard_token(client)
        state_response = client.post(
            f"/jobs/{failed.name}/state",
            auth=basic_auth(),
            data={"state": "production", "csrf_token": token},
            follow_redirects=False,
        )
        retry_response = client.post(
            f"/jobs/{failed.name}/retry",
            auth=basic_auth(),
            data={"csrf_token": token},
            follow_redirects=False,
        )
        preview_response = client.post(
            "/jobs/cleanup-test-jobs",
            auth=basic_auth(),
            data={"older_than_days": "7", "csrf_token": token},
        )
        archive_response = client.post(
            "/jobs/cleanup-test-jobs",
            auth=basic_auth(),
            data={
                "older_than_days": "7",
                "confirm": "archive",
                "csrf_token": token,
            },
        )

    assert state_response.status_code == 303
    assert retry_response.status_code == 303
    assert preview_response.status_code == 200
    assert archive_response.status_code == 200
    assert read_status(failed)["state"] == "production"
    assert read_status(failed)["status"] == "queued"
    assert read_status(old)["state"] == "archived"

    events = audit_events()
    names = [event["event"] for event in events]
    assert "admin.job.state" in names
    assert "admin.job.retry" in names
    assert names.count("admin.job.cleanup") == 2

    state_event = next(event for event in events if event["event"] == "admin.job.state")
    assert state_event["details"] == {
        "job_id": failed.name,
        "target_state": "production",
    }
    cleanup = [event for event in events if event["event"] == "admin.job.cleanup"]
    assert cleanup[0]["details"]["dry_run"] is True
    assert cleanup[1]["details"]["dry_run"] is False


def test_failed_basic_auth_rate_limit_recovers(
    secure_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(security_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("BOOK_SECURITY_AUTH_FAILURE_LIMIT", "2")
    monkeypatch.setenv("BOOK_SECURITY_AUTH_FAILURE_WINDOW_SECONDS", "10")
    reset_security_state()

    with TestClient(app) as client:
        first = client.get("/", auth=basic_auth("wrong-one"))
        second = client.get("/", auth=basic_auth("wrong-two"))
        blocked = client.get("/", auth=basic_auth())
        clock[0] += 11
        recovered = client.get("/", auth=basic_auth())

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["retry-after"] == "10"
    assert blocked.status_code == 429
    assert recovered.status_code == 200

    encoded = json.dumps(audit_events(), sort_keys=True)
    assert "wrong-one" not in encoded
    assert "wrong-two" not in encoded
    assert PRIVATE_PASSWORD not in encoded


def test_protected_request_rate_limit_recovers(
    secure_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [500.0]
    monkeypatch.setattr(security_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("BOOK_SECURITY_REQUEST_LIMIT", "2")
    monkeypatch.setenv("BOOK_SECURITY_REQUEST_WINDOW_SECONDS", "10")
    reset_security_state()

    with TestClient(app) as client:
        first = client.get("/", auth=basic_auth())
        second = client.get("/", auth=basic_auth())
        blocked = client.get("/", auth=basic_auth())
        health = client.get("/health")
        clock[0] += 11
        recovered = client.get("/", auth=basic_auth())

    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "request-rate-limit-exceeded"
    assert health.status_code == 200
    assert recovered.status_code == 200


def test_oversized_api_body_is_rejected_before_job_creation(
    secure_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_MAX_REQUEST_BYTES", "160")
    reset_security_state()

    with TestClient(app) as client:
        response = client.post(
            "/api/submit",
            headers={"x-api-key": PRIVATE_API_KEY},
            json={
                "title": "Oversized",
                "content": "x" * 1000,
            },
        )

    assert response.status_code == 413
    assert response.json()["code"] == "request-too-large"
    assert list((secure_root / "books" / "jobs").iterdir()) == []


def test_valid_api_key_operation_remains_compatible(secure_root: Path) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/submit",
            headers={"x-api-key": PRIVATE_API_KEY},
            json={"title": "API fixture", "content": "# API fixture"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "production"
    assert payload["status"] == "queued"
    assert (secure_root / "books" / "jobs" / payload["job_id"]).is_dir()


def test_audit_unavailability_blocks_dashboard_mutation(
    secure_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app) as client:
        token = dashboard_token(client)

        def refuse_open(*_args, **_kwargs):
            raise OSError("injected audit failure")

        monkeypatch.setattr(security_module.os, "open", refuse_open)
        response = client.post(
            "/submit-form",
            auth=basic_auth(),
            data={
                "title": "Must not exist",
                "content": "# Must not exist",
                "state": "test",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

    assert response.status_code == 503
    assert response.json()["code"] == "security-audit-unavailable"
    assert list((secure_root / "books" / "jobs").iterdir()) == []


def test_invalid_security_configuration_fails_closed_on_protected_route(
    secure_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SECURITY_CSRF_ENABLED", "maybe")

    with TestClient(app) as client:
        response = client.get("/", auth=basic_auth())

    assert response.status_code == 503
    assert response.json()["code"] == "invalid-security-config"


def test_existing_recovery_history_remains_operator_auditable(
    secure_root: Path,
) -> None:
    _, job = create_job(
        title="Recovery history",
        markdown="# Recovery history",
        state="test",
    )
    write_status(
        job,
        status="failed",
        step="recovered-interruption",
        message="Interrupted job marked failed by operator",
        extra={
            "last_recovered_by": "operator-name",
            "last_recovery_reason": "controlled acceptance",
            "recovery_count": 1,
        },
    )
    from app.services.job_queue import append_job_event

    append_job_event(
        job,
        "recovered",
        "Interrupted job marked failed by operator",
        target="failed",
        operator="operator-name",
        reason="controlled acceptance",
        recovery_count=1,
    )

    events = read_job_events(job)
    assert events[-1]["event"] == "recovered"
    assert events[-1]["operator"] == "operator-name"
    assert events[-1]["reason"] == "controlled acceptance"
    assert read_status(job)["last_recovered_by"] == "operator-name"
