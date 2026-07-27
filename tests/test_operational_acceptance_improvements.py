from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPOSITORY_ROOT / "scripts" / "audit_job_service_access.py"
REHEARSAL_ROOT_SCRIPT = REPOSITORY_ROOT / "scripts" / "prepare_rehearsal_root.py"
LIVE_REHEARSAL_SCRIPT = REPOSITORY_ROOT / "scripts" / "h09_live_rehearsal.sh"
DEPLOY_SCRIPT = REPOSITORY_ROOT / "scripts" / "deploy_server.sh"
WORKER_UNIT = REPOSITORY_ROOT / "deploy" / "systemd" / "book-system-worker.service"
FAILURE_UNIT = (
    REPOSITORY_ROOT
    / "deploy"
    / "systemd"
    / "book-system-worker-failure@.service"
)
PR_TEMPLATE = REPOSITORY_ROOT / ".github" / "pull_request_template.md"
RULES_DOCUMENT = REPOSITORY_ROOT / "docs" / "OPERATIONAL_ACCEPTANCE_RULES.md"


def load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_job_store(root: Path) -> Path:
    jobs = root / "books" / "jobs"
    job = jobs / "20260727-120000-deadbeef"
    (job / "output").mkdir(parents=True)
    (job / "logs").mkdir()
    (job / "status.json").write_text(
        json.dumps({"status": "done", "state": "production"}),
        encoding="utf-8",
    )
    (job / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (job / "logs" / "build.log").write_text("done\n", encoding="utf-8")
    (job / "output" / "book.pdf").write_bytes(b"pdf")
    return jobs


def test_service_account_audit_reports_aggregate_failures_without_paths(
    tmp_path: Path,
) -> None:
    module = load_script_module("job_access_audit_test", AUDIT_SCRIPT)
    jobs = make_job_store(tmp_path)

    def fake_runner(_user: str, path: Path, mode: str) -> bool:
        return not (path.name == "events.jsonl" and mode == "w")

    requirements, failures = module.audit_job_store(
        jobs,
        service_user="www-data",
        runner=fake_runner,
    )
    report = module.build_report(
        jobs,
        requirements,
        failures,
        include_paths=False,
    )

    assert report["status"] == "fail"
    assert report["jobs_checked"] == 1
    assert report["failure_count"] == 1
    assert report["failure_categories"] == {"file:w": 1}
    encoded = json.dumps(report, sort_keys=True)
    assert "deadbeef" not in encoded
    assert str(tmp_path) not in encoded


def test_service_account_audit_private_mode_can_name_relative_failure(
    tmp_path: Path,
) -> None:
    module = load_script_module("job_access_audit_private_test", AUDIT_SCRIPT)
    jobs = make_job_store(tmp_path)

    def fake_runner(_user: str, path: Path, mode: str) -> bool:
        return not (path.name == "status.json" and mode == "r")

    requirements, failures = module.audit_job_store(
        jobs,
        service_user="www-data",
        runner=fake_runner,
    )
    report = module.build_report(
        jobs,
        requirements,
        failures,
        include_paths=True,
    )

    assert report["failures"] == [
        {
            "path": "20260727-120000-deadbeef/status.json",
            "kind": "file",
            "mode": "r",
        }
    ]


def test_rehearsal_root_refuses_production_or_existing_target(
    tmp_path: Path,
) -> None:
    module = load_script_module("prepare_rehearsal_root_test", REHEARSAL_ROOT_SCRIPT)
    production = tmp_path / "production"
    production.mkdir()

    with pytest.raises(ValueError, match="outside production"):
        module.validate_target(production / "rehearsal", production)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        module.validate_target(existing, production)

    target, resolved_production = module.validate_target(
        tmp_path / "isolated-rehearsal",
        production,
    )
    assert target == tmp_path / "isolated-rehearsal"
    assert resolved_production == production


def test_worker_unit_bounds_restart_loop_and_emits_independent_alarm() -> None:
    worker = WORKER_UNIT.read_text(encoding="utf-8")
    alarm = FAILURE_UNIT.read_text(encoding="utf-8")

    assert "StartLimitIntervalSec=300" in worker
    assert "StartLimitBurst=3" in worker
    assert "OnFailure=book-system-worker-failure@%n" in worker
    assert "Restart=on-failure" in worker
    assert "book-system-worker-alarm" in alarm
    assert "/usr/bin/logger -p daemon.err" in alarm
    assert "NoNewPrivileges=true" in alarm
    assert "ProtectSystem=strict" in alarm


def test_exact_deploy_requires_reviewed_commit_and_service_access_audit() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    for required in (
        "--expected-commit",
        '[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$(git rev-parse origin/main)" == "$EXPECTED_COMMIT" ]]',
        'git merge --ff-only "$EXPECTED_COMMIT"',
        "audit_job_service_access.py",
        "book-system-worker-failure@.service",
        "StartLimitBurst",
        "StartLimitIntervalUSec",
        "OnFailure",
        "worker PID changed during stability window",
        "worker restart count increased",
    ):
        assert required in script

    assert "git pull" not in script
    assert "git reset --hard" not in script
    assert "git clean" not in script


def test_live_rehearsal_is_copied_guarded_and_stops_before_forward_deploy() -> None:
    script = LIVE_REHEARSAL_SCRIPT.read_text(encoding="utf-8")

    for required in (
        "set -Eeuo pipefail",
        "umask 077",
        "H09_REHEARSAL_COPIED=1",
        "rehearsal-scripts.sha256",
        "audit_job_service_access.py",
        "verify_worker_guard",
        "verify_worker_stability",
        'systemctl stop "$WORKER_SERVICE"',
        'wait_http_code "stopped-local-readiness" 503',
        "stopped-worker-readiness-sanitised=pass",
        "rollback_server.sh",
        '[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$TARGET_COMMIT" ]]',
        "next-protected-action=review evidence, then separately redeploy exact candidate",
    ):
        assert required in script

    lowered = script.lower()
    assert "git pull" not in lowered
    assert "git clean" not in lowered
    assert "git reset --hard" not in lowered
    assert "systemctl restart" not in lowered


def test_pr_template_prevents_premature_operational_issue_closure() -> None:
    template = PR_TEMPLATE.read_text(encoding="utf-8")
    rules = RULES_DOCUMENT.read_text(encoding="utf-8")

    assert "Relates to #<issue>" in template
    assert "Use `Closes`, `Fixes` or `Resolves` only" in template
    assert "Operational issues will be closed explicitly" in template
    assert "A pull request must use `Relates to #<issue>`" in rules
    assert "committed, reviewed and tested" in rules
    assert "isolated production-like root" in rules


@pytest.mark.parametrize(
    "script",
    [DEPLOY_SCRIPT, LIVE_REHEARSAL_SCRIPT],
)
def test_new_shell_runners_have_valid_bash_syntax(script: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    result = subprocess.run(
        [bash, "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
