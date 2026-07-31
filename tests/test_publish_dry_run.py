from __future__ import annotations

import tempfile
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.app as api_module
from app.api.app import app
from app.pipeline import exporters
from app.services import manuscript_validation, worker
from app.services.publish_plan import PUBLISH_OUTPUTS, publish_output_plan


def job_directories(root: Path) -> list[Path]:
    jobs = root / "books" / "jobs"
    if not jobs.exists():
        return []
    return sorted(path for path in jobs.iterdir() if path.is_dir())


def persistent_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def persistent_directories(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BOOK_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.delenv("BOOK_MAX_MANUSCRIPT_BYTES", raising=False)
    monkeypatch.delenv("BOOK_EXPORT_COMMAND_TIMEOUT_SECONDS", raising=False)
    return TestClient(app)


def install_successful_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    document = {
        "pandoc-api-version": [1, 23, 1],
        "meta": {
            "title": {"t": "MetaString", "c": "Dry Run"},
            "lang": {"t": "MetaString", "c": "en-GB"},
        },
        "blocks": [
            {
                "t": "Header",
                "c": [1, ["opening", [], []], [{"t": "Str", "c": "Opening"}]],
            },
            {"t": "Para", "c": [{"t": "Str", "c": "Body"}]},
        ],
    }
    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (document, False),
    )


def expected_manifest_outputs() -> dict[str, str]:
    return {output.key: output.filename for output in PUBLISH_OUTPUTS}


def install_forbidden_side_effect_blocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    forbid_validation: bool = False,
) -> list[str]:
    blocked_calls: list[str] = []

    def block_call(name: str):
        def _blocked(*_args: object, **_kwargs: object) -> None:
            blocked_calls.append(name)
            raise AssertionError(f"dry-run must not call {name}")

        return _blocked

    if forbid_validation:
        monkeypatch.setattr(
            api_module,
            "build_publish_dry_run",
            block_call("validation"),
        )
    monkeypatch.setattr(api_module, "create_job", block_call("create_job"))
    monkeypatch.setattr(exporters, "_run_export_command", block_call("export"))
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", block_call("temporary-file"))
    monkeypatch.setattr(tempfile, "TemporaryDirectory", block_call("temporary-dir"))
    monkeypatch.setattr(tempfile, "mkstemp", block_call("temporary-file"))
    monkeypatch.setattr(worker, "process_jobs", block_call("process_jobs"))
    monkeypatch.setattr(worker, "process_next_jobs", block_call("process_next_jobs"))
    return blocked_calls


def test_publish_dry_run_returns_authoritative_plan_without_retained_writes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)
    markdown = "---\ntitle: Dry Run\nlang: en-GB\n---\n\n# Opening\n\nBody.\n"
    files_before = persistent_files(tmp_path)
    directories_before = persistent_directories(tmp_path)

    response = client.post(
        "/api/v1/publish/dry-run",
        json={"title": "Dry Run", "content": markdown},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["publishable"] is True
    assert payload["validation"]["valid"] is True
    assert payload["validation"]["errors"] == []
    assert payload["validation"]["summary"]["source_bytes"] == len(
        markdown.encode("utf-8")
    )
    assert payload["outputs"] == publish_output_plan()
    assert {output["key"]: output["filename"] for output in payload["outputs"]} == (
        expected_manifest_outputs()
    )
    assert [output["media_type"] for output in payload["outputs"]] == [
        output.media_type for output in PUBLISH_OUTPUTS
    ]
    assert payload["source_bytes"] == len(markdown.encode("utf-8"))
    assert payload["source_sha256"] == sha256(markdown.encode("utf-8")).hexdigest()
    assert payload["job_state"] == "production"
    assert payload["rendering_attempted"] is False
    assert payload["job_created"] is False
    assert payload["contract_version"] == "0.2"
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == files_before
    assert persistent_directories(tmp_path) == directories_before


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"json": {"title": "Missing content"}},
        {"json": {"title": "Typed content", "content": {"not": "a string"}}},
        {
            "content": b'{"title":"Broken","content":',
            "headers": {"content-type": "application/json"},
        },
    ],
)
def test_publish_dry_run_malformed_requests_are_422_without_side_effects(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request_kwargs: dict[str, object],
) -> None:
    blocked_calls = install_forbidden_side_effect_blocks(
        monkeypatch,
        forbid_validation=True,
    )
    files_before = persistent_files(tmp_path)
    directories_before = persistent_directories(tmp_path)

    response = client.post("/api/v1/publish/dry-run", **request_kwargs)

    assert response.status_code == 422
    assert blocked_calls == []
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == files_before
    assert persistent_directories(tmp_path) == directories_before
    assert not (tmp_path / "books" / "jobs").exists()


def test_publish_dry_run_identical_requests_are_deterministic_without_retained_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)
    blocked_calls = install_forbidden_side_effect_blocks(monkeypatch)
    request = {
        "title": "Deterministic",
        "content": "---\ntitle: Deterministic\nlang: en-GB\n---\n\n# Opening\n\nSame.\n",
    }
    files_before = persistent_files(tmp_path)
    directories_before = persistent_directories(tmp_path)

    first = client.post("/api/v1/publish/dry-run", json=request)
    files_after_first = persistent_files(tmp_path)
    directories_after_first = persistent_directories(tmp_path)
    second = client.post("/api/v1/publish/dry-run", json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert blocked_calls == []
    assert job_directories(tmp_path) == []
    assert files_after_first == files_before
    assert directories_after_first == directories_before
    assert persistent_files(tmp_path) == files_before
    assert persistent_directories(tmp_path) == directories_before


def test_publish_dry_run_returns_non_publishable_http_200_without_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_if_called(_markdown: str) -> tuple[dict[str, object], bool]:
        raise AssertionError("Pandoc must not run for an empty dry-run manuscript")

    monkeypatch.setattr(manuscript_validation, "_parse_with_pandoc", fail_if_called)

    response = client.post(
        "/api/v1/publish/dry-run",
        json={"title": "Empty", "content": " \r\n\t"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["publishable"] is False
    assert payload["validation"]["valid"] is False
    assert [finding["code"] for finding in payload["validation"]["errors"]] == [
        "empty-manuscript"
    ]
    assert payload["outputs"] == publish_output_plan()
    assert payload["rendering_attempted"] is False
    assert payload["job_created"] is False
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == []


def test_publish_dry_run_requires_existing_api_authentication(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_successful_parser(monkeypatch)
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_API_KEY", "dry-run-key")
    payload = {"title": "Protected", "content": "# Protected\n"}

    assert client.post("/api/v1/publish/dry-run", json=payload).status_code == 403
    assert (
        client.post(
            "/api/v1/publish/dry-run",
            json=payload,
            headers={"x-api-key": "wrong"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/publish/dry-run",
        json=payload,
        headers={"x-api-key": "dry-run-key"},
    )
    assert response.status_code == 200
    assert response.json()["publishable"] is True


def test_publish_dry_run_reuses_request_and_manuscript_limits(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_API_KEY", "dry-run-key")
    request_payload = b'{"title":"Bounded","content":"# Bounded\\n"}'
    monkeypatch.setenv("BOOK_MAX_REQUEST_BYTES", str(len(request_payload)))
    headers = {
        "content-type": "application/json",
        "x-api-key": "dry-run-key",
    }

    accepted = client.post(
        "/api/v1/publish/dry-run",
        content=request_payload,
        headers=headers,
    )
    rejected = client.post(
        "/api/v1/publish/dry-run",
        content=request_payload + b" ",
        headers=headers,
    )

    assert accepted.status_code == 200
    assert accepted.json()["publishable"] is True
    assert rejected.status_code == 413
    assert rejected.json()["code"] == "request-too-large"
    assert rejected.json()["limit"] == len(request_payload)
    assert rejected.json()["actual"] == len(request_payload) + 1
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == []

    monkeypatch.setenv("BOOK_MAX_REQUEST_BYTES", "1000")
    monkeypatch.setenv("BOOK_MAX_MANUSCRIPT_BYTES", "4")
    too_large = client.post(
        "/api/v1/publish/dry-run",
        json={"title": "Too large", "content": "12345"},
        headers={"x-api-key": "dry-run-key"},
    )

    assert too_large.status_code == 413
    assert too_large.json()["code"] == "manuscript-too-large"
    assert too_large.json()["limit"] == 4
    assert too_large.json()["actual"] == 5
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == []


def test_publish_dry_run_validation_tool_failure_fails_closed_without_side_effects(
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
        "/api/v1/publish/dry-run",
        json={"title": "Unavailable", "content": "# Manuscript\n"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Pandoc is unavailable for manuscript validation",
        "code": "validation-tool-unavailable",
    }
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == []


def test_publish_dry_run_does_not_create_jobs_run_workers_or_export(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install_successful_parser(monkeypatch)
    blocked_calls = install_forbidden_side_effect_blocks(monkeypatch)

    response = client.post(
        "/api/v1/publish/dry-run",
        json={"title": "No effects", "content": "# No effects\n"},
    )

    assert response.status_code == 200
    assert blocked_calls == []
    assert job_directories(tmp_path) == []
    assert persistent_files(tmp_path) == []
    assert not (tmp_path / "books" / "jobs").exists()


def test_exporter_consumes_same_authoritative_output_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def capture(
        cmd: list[str],
        *,
        job_dir: Path,
        log_file: Path,
    ) -> None:
        assert job_dir == tmp_path
        assert log_file == tmp_path / "build.log"
        commands.append(cmd)

    monkeypatch.setattr(exporters, "_run_export_command", capture)
    markdown = tmp_path / "book.md"
    markdown.write_text("# Export\n", encoding="utf-8")

    outputs = exporters.pandoc_export(
        markdown,
        tmp_path / "output",
        tmp_path / "build.log",
    )

    assert outputs == expected_manifest_outputs()
    assert [Path(command[-1]).name for command in commands] == [
        output.filename for output in PUBLISH_OUTPUTS
    ]
    assert len(commands) == len(PUBLISH_OUTPUTS)
