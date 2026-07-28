from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.services import pandoc_capability
from app.services import readiness_guard
from app.services.manuscript_validation import (
    ValidationServiceError,
    _parse_with_pandoc,
    validate_manuscript,
)
from app.services.pandoc_capability import (
    PANDOC_DOCUMENTED_MINIMUM_VERSION,
    PandocSandboxCapability,
    pandoc_sandbox_command,
    probe_pandoc_sandbox,
)


class Completed:
    def __init__(
        self,
        *,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_documented_minimum_is_pandoc_2_15() -> None:
    assert PANDOC_DOCUMENTED_MINIMUM_VERSION == "2.15"


def test_pandoc_2_9_style_unsupported_sandbox_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], bytes]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs["input"]))
        return Completed(
            returncode=6,
            stderr=b"Unknown option --sandbox.\n",
        )

    monkeypatch.setattr(pandoc_capability.shutil, "which", lambda _name: "/bin/pandoc")
    monkeypatch.setattr(pandoc_capability.subprocess, "run", fake_run)

    capability = probe_pandoc_sandbox()

    assert capability.compatible is False
    assert capability.code == "pandoc-sandbox-unsupported"
    assert capability.return_code == 6
    assert len(calls) == 1
    assert calls[0][0] == [
        "/bin/pandoc",
        "--sandbox",
        "--from=markdown+yaml_metadata_block",
        "--to=json",
    ]
    assert calls[0][1].startswith(b"# Book System OS")


def test_compatible_pandoc_must_return_a_document_ast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "pandoc-api-version": [1, 23],
            "meta": {},
            "blocks": [],
        }
    ).encode("utf-8")

    monkeypatch.setattr(pandoc_capability.shutil, "which", lambda _name: "/bin/pandoc")
    monkeypatch.setattr(
        pandoc_capability.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(returncode=0, stdout=payload),
    )

    capability = probe_pandoc_sandbox()

    assert capability.compatible is True
    assert capability.code == "pandoc-sandbox-compatible"


def test_invalid_probe_json_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pandoc_capability.shutil, "which", lambda _name: "/bin/pandoc")
    monkeypatch.setattr(
        pandoc_capability.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(returncode=0, stdout=b"not-json"),
    )

    capability = probe_pandoc_sandbox()

    assert capability.compatible is False
    assert capability.code == "pandoc-sandbox-invalid-response"


def test_probe_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, float] = {}

    def fake_run(command, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(pandoc_capability.shutil, "which", lambda _name: "/bin/pandoc")
    monkeypatch.setattr(pandoc_capability.subprocess, "run", fake_run)

    capability = probe_pandoc_sandbox(timeout_seconds=900)

    assert capability.compatible is False
    assert capability.code == "pandoc-sandbox-probe-timeout"
    assert observed["timeout"] == 10.0


def test_readiness_fails_when_sandbox_capability_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_guard,
        "base_readiness_report",
        lambda now=None: {
            "ready": True,
            "status": "ready",
            "checked_at": "2026-07-28T00:00:00+00:00",
            "checks": {
                "configuration": {"status": "pass", "message": "ok"},
                "worker": {"status": "pass", "message": "ok", "worker_state": "idle"},
                "active_work": {"status": "pass", "message": "ok"},
                "pandoc": {"status": "pass", "message": "pandoc is available"},
            },
        },
    )
    monkeypatch.setattr(readiness_guard, "_unreadable_job_record_count", lambda: 0)
    monkeypatch.setattr(
        readiness_guard,
        "probe_pandoc_sandbox",
        lambda: PandocSandboxCapability(
            compatible=False,
            code="pandoc-sandbox-unsupported",
            message="Pandoc does not support the required sandbox capability",
            return_code=6,
        ),
    )

    report = readiness_guard.readiness_report()

    assert report["ready"] is False
    assert report["status"] == "not-ready"
    assert report["checks"]["pandoc"] == {
        "status": "fail",
        "message": "Pandoc does not support the required sandbox capability",
        "capability_code": "pandoc-sandbox-unsupported",
        "documented_minimum_version": "2.15",
    }


def test_readiness_passes_only_with_functional_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness_guard,
        "base_readiness_report",
        lambda now=None: {
            "ready": True,
            "status": "ready",
            "checked_at": "2026-07-28T00:00:00+00:00",
            "checks": {
                "configuration": {"status": "pass", "message": "ok"},
                "worker": {"status": "pass", "message": "ok", "worker_state": "idle"},
                "active_work": {"status": "pass", "message": "ok"},
                "pandoc": {"status": "pass", "message": "pandoc is available"},
            },
        },
    )
    monkeypatch.setattr(readiness_guard, "_unreadable_job_record_count", lambda: 0)
    monkeypatch.setattr(
        readiness_guard,
        "probe_pandoc_sandbox",
        lambda: PandocSandboxCapability(
            compatible=True,
            code="pandoc-sandbox-compatible",
            message="Pandoc sandbox capability is available",
            return_code=0,
        ),
    )

    report = readiness_guard.readiness_report()

    assert report["ready"] is True
    assert report["checks"]["pandoc"]["status"] == "pass"


def test_validation_has_no_unsandboxed_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 6, stdout="", stderr="Unknown option --sandbox")

    monkeypatch.setattr(
        "app.services.manuscript_validation.subprocess.run",
        fake_run,
    )

    with pytest.raises(ValidationServiceError) as exc_info:
        _parse_with_pandoc("# Test")

    assert exc_info.value.code == "validation-tool-failed"
    assert calls == [[
        "pandoc",
        "--sandbox",
        "--from=markdown+yaml_metadata_block",
        "--to=json",
    ]]


def test_real_installed_pandoc_performs_sandboxed_validation() -> None:
    capability = probe_pandoc_sandbox()
    assert capability.compatible is True, capability

    result = validate_manuscript(
        title="Real compatibility proof",
        markdown=(
            "---\n"
            "title: Real compatibility proof\n"
            "lang: en-GB\n"
            "---\n\n"
            "# Real compatibility proof\n\n"
            "A bounded real Pandoc validation.\n"
        ),
    )

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["summary"]["heading_count"] == 1


def test_install_and_deploy_use_shared_compatibility_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    install = (root / "scripts" / "install.sh").read_text(encoding="utf-8")
    deploy = (root / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")

    assert "check_runtime_compatibility.py\" --pandoc-only" in install
    assert "--fix-git-head-readability" in install
    assert "runuser -u www-data" in install

    assert "===== CURRENT RUNTIME COMPATIBILITY =====" in deploy
    assert "===== CANDIDATE RUNTIME COMPATIBILITY =====" in deploy
    assert "--fix-git-head-readability" in deploy
    assert "--expected-commit \"$EXPECTED_COMMIT\"" in deploy
    assert "runuser -u www-data" in deploy


def test_authoritative_command_always_contains_sandbox() -> None:
    command = pandoc_sandbox_command("/usr/local/bin/pandoc")

    assert command == (
        "/usr/local/bin/pandoc",
        "--sandbox",
        "--from=markdown+yaml_metadata_block",
        "--to=json",
    )
