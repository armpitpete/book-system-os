from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROLLBACK_SCRIPT = REPOSITORY_ROOT / "scripts" / "rollback_server.sh"
SNAPSHOT_SCRIPT = REPOSITORY_ROOT / "scripts" / "snapshot_job_integrity.py"
VERIFY_SCRIPT = REPOSITORY_ROOT / "scripts" / "verify_job_downloads.py"
VERIFY_LOGS_SCRIPT = REPOSITORY_ROOT / "scripts" / "verify_operational_logs.py"


def load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_completed_job(root: Path, job_id: str = "20260727-120000-deadbeef") -> Path:
    job = root / "books" / "jobs" / job_id
    for directory in ("input", "work", "output", "logs"):
        (job / directory).mkdir(parents=True, exist_ok=True)

    (job / "input" / "book.md").write_text("# Evidence\n", encoding="utf-8")
    (job / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "title": "Rollback evidence",
                "created_at": "2026-07-27T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (job / "status.json").write_text(
        json.dumps(
            {
                "state": "production",
                "status": "done",
                "step": "complete",
                "message": "Build complete",
            }
        ),
        encoding="utf-8",
    )
    outputs = {
        "pdf_standard": "book-standard.pdf",
        "pdf_nd": "book-nd.pdf",
        "epub": "book.epub",
        "docx": "book.docx",
    }
    for index, filename in enumerate(outputs.values(), start=1):
        (job / "output" / filename).write_bytes((filename.encode("utf-8") + b"\n") * index)
    (job / "manifest.json").write_text(
        json.dumps(
            {
                "completed_at": "2026-07-27T12:01:00+00:00",
                "outputs": outputs,
                "status": {"status": "done", "step": "complete"},
            }
        ),
        encoding="utf-8",
    )
    (job / "logs" / "build.log").write_text("build complete\n", encoding="utf-8")
    (job / "events.jsonl").write_text(
        json.dumps({"event": "completed", "created_at": "2026-07-27T12:01:00+00:00"})
        + "\n",
        encoding="utf-8",
    )
    return job


def make_log_snapshot(logs_root: Path, output: Path) -> None:
    files: dict[str, dict[str, object]] = {}
    for path in sorted(logs_root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            files[path.relative_to(logs_root).as_posix()] = {
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
    output.write_text(
        json.dumps({"version": 1, "files": files}, sort_keys=True),
        encoding="utf-8",
    )


def write_worker_heartbeat(
    path: Path,
    *,
    worker_id: str,
    heartbeat_at: str,
    state: str = "idle",
) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "worker_id": worker_id,
                "started_at": "2026-07-27T17:48:00+00:00",
                "heartbeat_at": heartbeat_at,
                "state": state,
            }
        ),
        encoding="utf-8",
    )


def test_completed_job_snapshot_is_deterministic_and_excludes_lock(tmp_path: Path) -> None:
    module = load_script_module("snapshot_job_integrity_test", SNAPSHOT_SCRIPT)
    job = make_completed_job(tmp_path)
    (job / ".lock").write_text("transient", encoding="utf-8")

    first = module.snapshot_job(job)
    second = module.snapshot_job(job)

    assert first == second
    assert first["job_id"] == job.name
    assert first["status"] == "done"
    assert ".lock" not in first["files"]
    assert "input/book.md" in first["files"]
    assert "metadata.json" in first["files"]
    assert "manifest.json" in first["files"]
    assert set(path for path in first["files"] if path.startswith("output/")) == {
        "output/book-standard.pdf",
        "output/book-nd.pdf",
        "output/book.epub",
        "output/book.docx",
    }


def test_snapshot_refuses_non_completed_job_and_symlink(tmp_path: Path) -> None:
    module = load_script_module("snapshot_job_integrity_failure_test", SNAPSHOT_SCRIPT)
    job = make_completed_job(tmp_path)
    status_path = job / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["status"] = "running"
    status_path.write_text(json.dumps(status), encoding="utf-8")

    with pytest.raises(module.SnapshotError, match="must be completed"):
        module.snapshot_job(job)

    status["status"] = "done"
    status_path.write_text(json.dumps(status), encoding="utf-8")
    link = job / "logs" / "linked.log"
    try:
        link.symlink_to(job / "logs" / "build.log")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(module.SnapshotError, match="symbolic link"):
        module.snapshot_job(job)


def test_download_verifier_matches_retained_outputs_without_reporting_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_script_module("verify_job_downloads_test", VERIFY_SCRIPT)
    job = make_completed_job(tmp_path)
    env_file = tmp_path / "config" / "env"
    env_file.parent.mkdir()
    env_file.write_text(
        "BOOK_ADMIN_USERNAME=operator\nBOOK_ADMIN_PASSWORD=private-password\n",
        encoding="utf-8",
    )

    expected: dict[str, bytes] = {
        f"/jobs/{job.name}": f"<h1>Job {job.name}</h1>".encode("utf-8"),
    }
    for output in (job / "output").iterdir():
        expected[f"/jobs/{job.name}/output/{output.name}"] = output.read_bytes()

    calls: list[str] = []

    def fake_get(url: str, username: str, password: str) -> bytes:
        assert username == "operator"
        assert password == "private-password"
        path = module.urlparse(url).path
        calls.append(path)
        return expected[path]

    monkeypatch.setattr(module, "authenticated_get", fake_get)
    report = module.verify_job(
        root=tmp_path,
        job_id=job.name,
        base_url="http://127.0.0.1:8080",
        env_file=env_file,
    )

    encoded = json.dumps(report, sort_keys=True)
    assert report["detail"] == "pass"
    assert len(report["downloads"]) == 4
    assert len(calls) == 5
    assert "operator" not in encoded
    assert "private-password" not in encoded


def test_download_verifier_refuses_non_local_credential_destination(tmp_path: Path) -> None:
    module = load_script_module("verify_job_downloads_remote_test", VERIFY_SCRIPT)
    job = make_completed_job(tmp_path)
    env_file = tmp_path / "config" / "env"
    env_file.parent.mkdir()
    env_file.write_text(
        "BOOK_ADMIN_USERNAME=operator\nBOOK_ADMIN_PASSWORD=private-password\n",
        encoding="utf-8",
    )

    with pytest.raises(module.VerificationError, match="only to a local HTTP endpoint"):
        module.verify_job(
            root=tmp_path,
            job_id=job.name,
            base_url="https://publish.toiletrage.co.uk",
            env_file=env_file,
        )


def test_operational_log_verifier_allows_heartbeat_replacement_and_log_append(
    tmp_path: Path,
) -> None:
    module = load_script_module("verify_operational_logs_test", VERIFY_LOGS_SCRIPT)
    logs = tmp_path / "logs"
    logs.mkdir()
    build_log = logs / "worker.log"
    heartbeat = logs / "worker-heartbeat.json"
    build_log.write_text("before\n", encoding="utf-8")
    write_worker_heartbeat(
        heartbeat,
        worker_id="worker-before",
        heartbeat_at="2026-07-27T17:48:01+00:00",
    )
    snapshot = tmp_path / "logs-before.json"
    make_log_snapshot(logs, snapshot)

    build_log.write_text("before\nafter\n", encoding="utf-8")
    write_worker_heartbeat(
        heartbeat,
        worker_id="worker-after",
        heartbeat_at="2026-07-27T18:03:05+00:00",
    )

    report = module.verify_operational_logs(
        before_path=snapshot,
        logs_root=logs,
    )

    assert report["append_only_logs_preserved"] == 1
    assert report["mutable_state_files_validated"] == ["worker-heartbeat.json"]
    assert report["worker_heartbeat"]["state"] == "idle"
    assert report["worker_heartbeat"]["worker_id_present"] is True


def test_operational_log_verifier_refuses_replaced_append_only_log(
    tmp_path: Path,
) -> None:
    module = load_script_module("verify_operational_logs_replaced_test", VERIFY_LOGS_SCRIPT)
    logs = tmp_path / "logs"
    logs.mkdir()
    build_log = logs / "worker.log"
    heartbeat = logs / "worker-heartbeat.json"
    build_log.write_text("before\n", encoding="utf-8")
    write_worker_heartbeat(
        heartbeat,
        worker_id="worker-before",
        heartbeat_at="2026-07-27T17:48:01+00:00",
    )
    snapshot = tmp_path / "logs-before.json"
    make_log_snapshot(logs, snapshot)

    build_log.write_text("replacement\n", encoding="utf-8")
    write_worker_heartbeat(
        heartbeat,
        worker_id="worker-after",
        heartbeat_at="2026-07-27T18:03:05+00:00",
    )

    with pytest.raises(
        module.OperationalLogVerificationError,
        match="replaced or truncated",
    ):
        module.verify_operational_logs(
            before_path=snapshot,
            logs_root=logs,
        )


def test_operational_log_verifier_refuses_invalid_replacement_heartbeat(
    tmp_path: Path,
) -> None:
    module = load_script_module("verify_operational_logs_heartbeat_test", VERIFY_LOGS_SCRIPT)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "worker.log").write_text("before\n", encoding="utf-8")
    heartbeat = logs / "worker-heartbeat.json"
    write_worker_heartbeat(
        heartbeat,
        worker_id="worker-before",
        heartbeat_at="2026-07-27T17:48:01+00:00",
    )
    snapshot = tmp_path / "logs-before.json"
    make_log_snapshot(logs, snapshot)

    heartbeat.write_text('{"version": 1, "state": "idle"}', encoding="utf-8")

    with pytest.raises(
        module.OperationalLogVerificationError,
        match="worker_id is missing",
    ):
        module.verify_operational_logs(
            before_path=snapshot,
            logs_root=logs,
        )


def test_rollback_script_contains_required_protection_and_no_destructive_cleanup() -> None:
    script = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

    for required in (
        '--confirm exact-rollback',
        '[[ "$EXPECTED_CURRENT" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$TARGET_COMMIT" =~ ^[0-9a-f]{40}$ ]]',
        'stat -c \'%a\' "$ROOT_DIR/config/env"',
        'stat -c \'%U:%G\' "$ROOT_DIR/config/env"',
        'git status --porcelain --untracked-files=all',
        'git merge-base --is-ancestor "$TARGET_COMMIT" "$EXPECTED_CURRENT"',
        'git ls-files -- config/env books/jobs logs',
        'systemctl show --property=EnvironmentFiles',
        'systemctl show --property=ExecStart',
        'systemctl show --property=ReadWritePaths',
        'systemctl show --property=NoNewPrivileges',
        'systemctl show --property=ProtectSystem',
        'systemctl stop "$API_SERVICE" "$WORKER_SERVICE"',
        'git reset --hard "$TARGET_COMMIT"',
        'sha256sum "$ROOT_DIR/config/env"',
        'cmp -s "$EVIDENCE_DIR/store-before.json" "$EVIDENCE_DIR/store-after-reset.json"',
        'cmp -s "$EVIDENCE_DIR/job-before.json" "$EVIDENCE_DIR/job-after.json"',
        'verify_job_downloads.py',
        'verify_operational_logs.py',
        'logs-after-service-recovery.json',
        'wait_url "public-readiness"',
        'rollback-result=PASS',
    ):
        assert required in script

    assert "verify_logs_not_replaced" not in script
    lowered = script.lower()
    for forbidden in (
        "git clean",
        "rm -rf",
        "shred",
        "cp config/env",
        "cp -r books",
        "rsync --delete",
    ):
        assert forbidden not in lowered
    assert script.count('git reset --hard "$TARGET_COMMIT"') == 1


def test_rollback_script_has_valid_bash_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    result = subprocess.run(
        [bash, "-n", str(ROLLBACK_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
