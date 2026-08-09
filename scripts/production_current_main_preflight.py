from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
API_SERVICE = "book-system-api.service"
WORKER_SERVICE = "book-system-worker.service"
DEFAULT_PUBLIC_BASE = "https://publish.toiletrage.co.uk"
DEFAULT_REPO_ROOT = Path("/opt/book-system")
DEFAULT_ENV_FILE = Path("/opt/book-system/config/env")
DEFAULT_RELEASE_PARENT = Path("/var/tmp")
DEFAULT_EVIDENCE_PARENT = Path("/var/log/book-system")
READINESS_MIN_FREE_DEFAULT = 536_870_912
ENV_KEYS = {
    "BOOK_BIND_PORT",
    "BOOK_READINESS_MIN_FREE_BYTES",
    "BOOK_MAX_TOTAL_STORAGE_BYTES",
}


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class TreeSnapshot:
    digest: str
    entries: int
    bytes: int


def fail(message: str) -> None:
    raise PreflightError(message)


def validate_sha(value: str, label: str) -> str:
    value = value.strip()
    if not SHA_RE.fullmatch(value):
        fail(f"{label} must be a full lowercase SHA-1")
    return value


def run(
    command: Sequence[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"command could not complete: {command[0]} ({type(exc).__name__})")
    if check and completed.returncode != 0:
        fail(f"command failed: {command[0]}")
    return completed


def git(root: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(root), *args], timeout=60, check=check).stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_env(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        fail("protected environment file is unavailable or unsafe")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def positive_int(values: dict[str, str], key: str, default: int | None = None) -> int:
    raw = values.get(key)
    if raw is None:
        if default is None:
            fail(f"required numeric setting is unavailable: {key}")
        return default
    try:
        value = int(raw)
    except ValueError:
        fail(f"{key} is not an integer")
    if value <= 0:
        fail(f"{key} must be positive")
    return value


def snapshot_tree(root: Path, *, skip_gitkeep: bool = False) -> TreeSnapshot:
    records: list[dict[str, Any]] = []
    byte_count = 0
    if not root.exists():
        payload = b"[]\n"
        return TreeSnapshot(hashlib.sha256(payload).hexdigest(), 0, 0)
    if root.is_symlink() or not root.is_dir():
        fail(f"unsafe retained-state root: {root}")
    for current_raw, dirs, files in os.walk(root, followlinks=False):
        current = Path(current_raw)
        dirs.sort()
        files.sort()
        for name in dirs:
            path = current / name
            if path.is_symlink():
                fail(f"retained-state symlink is not allowed: {path}")
            st = path.stat()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "directory",
                    "mode": stat.S_IMODE(st.st_mode),
                }
            )
        for name in files:
            if skip_gitkeep and name == ".gitkeep":
                continue
            path = current / name
            if path.is_symlink():
                fail(f"retained-state symlink is not allowed: {path}")
            if not path.is_file():
                fail(f"unsafe retained-state entry: {path}")
            st = path.stat()
            byte_count += st.st_size
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "file",
                    "mode": stat.S_IMODE(st.st_mode),
                    "bytes": st.st_size,
                    "sha256": sha256_file(path),
                }
            )
    payload = (
        json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return TreeSnapshot(hashlib.sha256(payload).hexdigest(), len(records), byte_count)


def job_state(jobs_root: Path) -> dict[str, Any]:
    if jobs_root.is_symlink() or not jobs_root.is_dir():
        fail("retained jobs root is unavailable or unsafe")
    jobs = 0
    active: list[str] = []
    locks: list[str] = []
    for path in sorted(jobs_root.iterdir()):
        if path.is_symlink():
            fail(f"job symlink is not allowed: {path}")
        if not path.is_dir():
            continue
        jobs += 1
        if (path / ".lock").exists():
            locks.append(path.name)
        status_path = path / "status.json"
        if not status_path.is_file():
            continue
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"unreadable retained status record: {path.name} ({type(exc).__name__})")
        if isinstance(payload, dict) and payload.get("status") in {"queued", "running"}:
            active.append(path.name)
    return {
        "job_count": jobs,
        "active_job_count": len(active),
        "locked_job_count": len(locks),
    }


def check_release_wrapper(path: Path, target: str) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        fail("target release wrapper is unavailable or unsafe")
    text = path.read_text(encoding="utf-8")
    required = (
        "--expected-before",
        "--target-commit",
        "--confirm",
        "DEPLOY $TARGET_COMMIT",
        "image_holder_rendering_v0_2_live_acceptance=pass",
        "actual_book_readiness_claimed=false",
    )
    missing = [item for item in required if item not in text]
    if missing:
        fail("target release wrapper contract is incomplete")
    return {
        "sha256": sha256_file(path),
        "contract": "pass",
        "target": target,
    }


def remote_main(remote: str) -> str:
    completed = run(["git", "ls-remote", remote, "refs/heads/main"], timeout=60)
    fields = completed.stdout.strip().split()
    if len(fields) != 2 or fields[1] != "refs/heads/main":
        fail("remote main could not be resolved exactly")
    return validate_sha(fields[0], "remote main")


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status != 200:
                fail(f"HTTP probe returned {response.status}: {url}")
            raw = response.read()
    except urllib.error.HTTPError as exc:
        fail(f"HTTP probe returned {exc.code}: {url}")
    except OSError as exc:
        fail(f"HTTP probe failed: {url} ({type(exc).__name__})")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"HTTP probe did not return JSON: {url}")
    if not isinstance(payload, dict):
        fail(f"HTTP probe did not return an object: {url}")
    return payload


def systemctl_active(unit: str) -> None:
    run(["systemctl", "is-active", "--quiet", unit])


def systemctl_value(unit: str, property_name: str) -> str:
    return run(
        ["systemctl", "show", unit, f"--property={property_name}", "--value"]
    ).stdout.strip()


def check_worker_window(seconds: int) -> dict[str, Any]:
    systemctl_active(WORKER_SERVICE)
    pid_before = systemctl_value(WORKER_SERVICE, "MainPID")
    restarts_before = systemctl_value(WORKER_SERVICE, "NRestarts")
    if not pid_before.isdigit() or int(pid_before) <= 0:
        fail("worker has no live PID")
    if not restarts_before.isdigit():
        fail("worker restart count is invalid")
    time.sleep(seconds)
    systemctl_active(WORKER_SERVICE)
    pid_after = systemctl_value(WORKER_SERVICE, "MainPID")
    restarts_after = systemctl_value(WORKER_SERVICE, "NRestarts")
    if pid_after != pid_before:
        fail("worker PID changed during preflight stability window")
    if restarts_after != restarts_before:
        fail("worker restart count increased during preflight")
    return {
        "pid": int(pid_after),
        "restarts": int(restarts_after),
        "stability_seconds": seconds,
    }


def check_var_tmp(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
        fail("release-worktree parent is not writable/traversable")
    findmnt = run(
        ["findmnt", "-n", "-o", "FSTYPE,OPTIONS", "-T", str(path)],
        check=False,
    )
    if findmnt.returncode != 0:
        fail("release-worktree mount options could not be inspected")
    output = findmnt.stdout.strip()
    options = output.split(None, 1)[1] if " " in output else ""
    option_set = set(options.split(","))
    if "noexec" in option_set or "ro" in option_set:
        fail("release-worktree parent is mounted noexec or read-only")
    probe = path / f".book-system-preflight-{os.getpid()}"
    try:
        probe.mkdir(mode=0o700)
        script = probe / "probe.sh"
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o700)
        completed = run([str(script)], check=False)
        if completed.returncode != 0:
            fail("release-worktree execution probe failed")
    finally:
        if probe.exists():
            shutil.rmtree(probe)
    return {"path": str(path), "mount": output, "suitable": True}


def load_requirement_plan(candidate_root: Path, current: Path) -> dict[str, Any]:
    module_path = candidate_root / "scripts" / "reconcile_runtime_requirements.py"
    if module_path.is_symlink() or not module_path.is_file():
        fail("target requirement planner is unavailable")
    spec = importlib.util.spec_from_file_location("bos_preflight_requirements", module_path)
    if spec is None or spec.loader is None:
        fail("target requirement planner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        candidate_requirements = module.parse_requirements(candidate_root / "requirements.txt")
        plan = module.plan_reconciliation(current, candidate_root / "requirements.txt")
    except Exception as exc:
        fail(f"runtime requirement plan failed: {type(exc).__name__}")
    return {
        "current_sha256": plan.current_sha256,
        "candidate_sha256": plan.candidate_sha256,
        "policy": plan.policy,
        "additions": [item.raw for item in plan.additions],
        "pillow_version": next(
            (item.version for item in candidate_requirements if item.identity == "pillow"),
            None,
        ),
    }


def write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def default_evidence(target: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_EVIDENCE_PARENT / f"preflight-{timestamp}-{target[:12]}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only exact-state production preflight for Book System OS."
    )
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    parser.add_argument("--expected-before", required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE)
    parser.add_argument("--release-worktree-parent", type=Path, default=DEFAULT_RELEASE_PARENT)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--stability-seconds", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    expected = validate_sha(args.expected_before, "expected-before")
    target = validate_sha(args.target_commit, "target-commit")
    if expected == target:
        fail("expected-before and target must differ")
    if not 1 <= args.stability_seconds <= 60:
        fail("stability-seconds must be within 1..60")
    if os.geteuid() != 0:
        fail("production preflight must run as root")

    candidate_root = Path(__file__).resolve().parents[1]
    repo_root = args.repo_root.resolve()
    env_file = args.env_file.absolute()
    evidence_dir = (args.evidence_dir or default_evidence(target)).resolve()
    if evidence_dir.exists():
        fail("evidence directory already exists")
    evidence_dir.mkdir(parents=True, mode=0o700)
    evidence_dir.chmod(0o700)

    report: dict[str, Any] = {
        "contract": "production-current-main-preflight-v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "expected_before": expected,
        "target_commit": target,
        "deployment_authorized": False,
        "checks": {},
    }
    result_path = evidence_dir / "result.txt"
    report_path = evidence_dir / "preflight.json"

    try:
        if not (repo_root / ".git").exists():
            fail("production repository is unavailable")
        if git(repo_root, "rev-parse", "HEAD") != expected:
            fail("production HEAD is not the exact expected predecessor")
        if git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD") != "main":
            fail("production checkout is not on main")
        if git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
            fail("production checkout is not clean")
        report["checks"]["production_repository"] = {
            "head": expected, "branch": "main", "clean": True
        }

        if git(candidate_root, "rev-parse", "HEAD") != target:
            fail("preflight command is not running from the exact target commit")
        if git(candidate_root, "status", "--porcelain=v1", "--untracked-files=all"):
            fail("target candidate worktree is not clean")
        report["checks"]["candidate"] = {"head": target, "clean": True}

        remote = git(repo_root, "remote", "get-url", "origin")
        observed_remote_main = remote_main(remote)
        if observed_remote_main != target:
            fail("remote main is not the exact target")
        if run(
            ["git", "-C", str(candidate_root), "merge-base", "--is-ancestor", expected, target],
            check=False,
        ).returncode != 0:
            fail("target is not a descendant of production predecessor")
        report["checks"]["authority"] = {
            "remote_main": target, "ancestry": "pass"
        }

        env_stat = env_file.stat()
        if stat.S_IMODE(env_stat.st_mode) != 0o600:
            fail("protected environment mode is not 600")
        if env_stat.st_uid != 0 or env_stat.st_gid != 0:
            fail("protected environment owner is not root:root")
        config_hash_before = sha256_file(env_file)
        values = selected_env(env_file)
        port = positive_int(values, "BOOK_BIND_PORT")
        if not 1 <= port <= 65535:
            fail("BOOK_BIND_PORT is outside 1..65535")
        report["checks"]["protected_config"] = {
            "mode": "600",
            "owner": "root:root",
            "sha256": config_hash_before,
        }

        systemctl_active(API_SERVICE)
        systemctl_active(WORKER_SERVICE)
        local = f"http://127.0.0.1:{port}"
        public = args.public_base_url.rstrip("/")
        local_health = request_json(f"{local}/health")
        local_ready = request_json(f"{local}/ready")
        public_health = request_json(f"{public}/health")
        public_ready = request_json(f"{public}/ready")
        if local_health.get("status") != "ok" or public_health.get("status") != "ok":
            fail("health contract did not pass")
        if local_ready.get("ready") is not True or public_ready.get("ready") is not True:
            fail("readiness contract did not pass")
        report["checks"]["services"] = {
            "api": "active",
            "worker": "active",
            "local_health": "pass",
            "local_ready": "pass",
            "public_health": "pass",
            "public_ready": "pass",
        }
        worker = check_worker_window(args.stability_seconds)
        report["checks"]["worker_stability"] = worker

        python_bin = repo_root / ".venv" / "bin" / "python"
        if not python_bin.is_file() or not os.access(python_bin, os.X_OK):
            fail("production virtualenv Python is unavailable")
        requirement_plan = load_requirement_plan(
            candidate_root, repo_root / "requirements.txt"
        )
        report["checks"]["requirements"] = requirement_plan
        run([str(python_bin), "-m", "pip", "check", "--disable-pip-version-check"], timeout=60)
        run(
            ["runuser", "-u", "www-data", "--", str(python_bin), "-m", "pip", "check",
             "--disable-pip-version-check"],
            timeout=60,
        )
        pil_root = run(
            [str(python_bin), "-c", "import PIL; print(PIL.__version__)"]
        ).stdout.strip()
        pil_service = run(
            ["runuser", "-u", "www-data", "--", str(python_bin), "-c",
             "import PIL; print(PIL.__version__)"]
        ).stdout.strip()
        if pil_root != pil_service:
            fail("Pillow version differs between root and service account")
        expected_pillow = requirement_plan.get("pillow_version")
        if expected_pillow and pil_root != expected_pillow:
            fail("production Pillow version does not match candidate requirement")
        report["checks"]["virtualenv"] = {
            "pip_check": "pass",
            "service_account_pip_check": "pass",
            "pillow_version": pil_root,
            "service_account_pillow_import": "pass",
        }

        pandoc = Path("/opt/book-system-runtime/pandoc/current/bin/pandoc")
        if not pandoc.is_file() or not os.access(pandoc, os.X_OK):
            fail("pinned Pandoc runtime is unavailable")
        pandoc_version = run([str(pandoc), "--version"]).stdout.splitlines()[0]
        run(["runuser", "-u", "www-data", "--", str(pandoc), "--version"])
        xelatex_path = shutil.which("xelatex")
        if not xelatex_path:
            fail("XeLaTeX is unavailable")
        xelatex_version = run([xelatex_path, "--version"]).stdout.splitlines()[0]
        run(["runuser", "-u", "www-data", "--", xelatex_path, "--version"])
        report["checks"]["toolchain"] = {
            "pandoc": pandoc_version,
            "pandoc_service_account": "pass",
            "xelatex": xelatex_version,
            "xelatex_service_account": "pass",
        }

        jobs_root = repo_root / "books" / "jobs"
        revisions_root = repo_root / "books" / "revisions"
        jobs_before = snapshot_tree(jobs_root)
        revisions_before = snapshot_tree(revisions_root, skip_gitkeep=True)
        job_counts = job_state(jobs_root)
        if job_counts["active_job_count"] or job_counts["locked_job_count"]:
            fail("active or locked jobs prevent release preflight")
        report["checks"]["retained_state"] = {
            **job_counts,
            "jobs_digest": jobs_before.digest,
            "jobs_entries": jobs_before.entries,
            "jobs_bytes": jobs_before.bytes,
            "revision_digest": revisions_before.digest,
            "revision_entries": revisions_before.entries,
            "revision_bytes": revisions_before.bytes,
        }

        disk = shutil.disk_usage(repo_root)
        min_free = positive_int(
            values, "BOOK_READINESS_MIN_FREE_BYTES", READINESS_MIN_FREE_DEFAULT
        )
        max_storage = positive_int(values, "BOOK_MAX_TOTAL_STORAGE_BYTES")
        if disk.free < min_free:
            fail("production disk free space is below readiness minimum")
        if jobs_before.bytes > max_storage:
            fail("retained jobs exceed configured total storage limit")
        report["checks"]["capacity"] = {
            "free_bytes": disk.free,
            "minimum_free_bytes": min_free,
            "retained_job_bytes": jobs_before.bytes,
            "maximum_retained_bytes": max_storage,
        }

        report["checks"]["release_worktree"] = check_var_tmp(
            args.release_worktree_parent
        )
        wrapper = check_release_wrapper(
            candidate_root / "scripts" / "production_current_main_release.sh",
            target,
        )
        report["checks"]["release_wrapper"] = wrapper

        if git(repo_root, "rev-parse", "HEAD") != expected:
            fail("production HEAD changed during preflight")
        if git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
            fail("production checkout changed during preflight")
        if sha256_file(env_file) != config_hash_before:
            fail("protected environment changed during preflight")
        jobs_after = snapshot_tree(jobs_root)
        revisions_after = snapshot_tree(revisions_root, skip_gitkeep=True)
        if jobs_after != jobs_before:
            fail("retained job state changed during preflight")
        if revisions_after != revisions_before:
            fail("Revision Studio state changed during preflight")
        systemctl_active(API_SERVICE)
        systemctl_active(WORKER_SERVICE)
        final_pid = systemctl_value(WORKER_SERVICE, "MainPID")
        final_restarts = systemctl_value(WORKER_SERVICE, "NRestarts")
        if final_pid != str(worker["pid"]) or final_restarts != str(worker["restarts"]):
            fail("worker changed after stability observation")
        run([str(python_bin), "-m", "pip", "check", "--disable-pip-version-check"], timeout=60)
        report["checks"]["final_invariants"] = {
            "production_head": expected,
            "production_clean": True,
            "config_unchanged": True,
            "retained_jobs_unchanged": True,
            "revision_state_unchanged": True,
            "api_active": True,
            "worker_active": True,
            "worker_pid": int(final_pid),
            "worker_restarts": int(final_restarts),
            "pip_check": "pass",
        }

        report["status"] = "PASS"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_private(
            report_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        write_private(
            result_path,
            "\n".join(
                [
                    "PASS",
                    f"expected_before={expected}",
                    f"target_commit={target}",
                    f"production_head={expected}",
                    f"remote_main={target}",
                    f"retained_jobs_digest={jobs_before.digest}",
                    f"revision_state_digest={revisions_before.digest}",
                    f"config_sha256={config_hash_before}",
                    f"release_wrapper_sha256={wrapper['sha256']}",
                    "FRESH-PRODUCTION-PREFLIGHT=PASS",
                    "deployment-authorized=false",
                    "",
                ]
            ),
        )
        print("FRESH-PRODUCTION-PREFLIGHT=PASS")
        print(f"expected-before={expected}")
        print(f"target-commit={target}")
        print(f"evidence={evidence_dir}")
        print("deployment-authorized=false")
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, PreflightError) else f"{type(exc).__name__}"
        report["status"] = "FAIL"
        report["error"] = message
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_private(
            report_path, json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        write_private(result_path, f"FAIL\n{message}\ndeployment-authorized=false\n")
        if isinstance(exc, PreflightError):
            raise
        raise PreflightError(message) from None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
