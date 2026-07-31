from __future__ import annotations

import os
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

import pytest

from scripts import v2_01_live_acceptance as acceptance


PINNED_RUNTIME_PATH = (
    "/opt/book-system-runtime/pandoc/current/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


def _require_command(name: str) -> str:
    if name == "bash":
        configured = os.environ.get("BOOK_SYSTEM_TEST_BASH")
        candidates = [
            Path(configured) if configured else None,
            Path("C:/msys64/usr/bin/bash.exe"),
        ]
        for candidate in candidates:
            if candidate is not None and candidate.is_file():
                return str(candidate)
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is unavailable")
    return path


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _git(repo: Path, *args: str) -> str:
    git = _require_command("git")
    result = _run([git, *args], cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _bash_path(bash: str, path: Path) -> str:
    if os.name != "nt":
        return path.as_posix()
    result = _run(
        [bash, "-lc", 'printf "BOOK_SYSTEM_PATH:%s\n" "$(cygpath -u "$1")"', "_", str(path)],
    )
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("BOOK_SYSTEM_PATH:"):
            return line.partition(":")[2]
    raise AssertionError(result.stdout)


def test_read_env_value_does_not_execute_the_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    marker = tmp_path / "must-not-exist"
    env_file.write_text(
        "# protected settings\n"
        "BOOK_API_KEY='correct-key'\n"
        f"UNRELATED=$(touch {marker})\n",
        encoding="utf-8",
    )

    assert acceptance.read_env_value(env_file, "BOOK_API_KEY") == "correct-key"
    assert marker.exists() is False


def test_read_env_value_rejects_duplicate_or_empty_values(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    duplicate.write_text("BOOK_API_KEY=one\nBOOK_API_KEY=two\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly once"):
        acceptance.read_env_value(duplicate, "BOOK_API_KEY")

    empty = tmp_path / "empty"
    empty.write_text("BOOK_API_KEY=\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly once"):
        acceptance.read_env_value(empty, "BOOK_API_KEY")


def test_storage_manifest_detects_content_and_structure_changes(tmp_path: Path) -> None:
    books = tmp_path / "books"
    job = books / "jobs" / "job-1"
    job.mkdir(parents=True)
    status = job / "status.json"
    status.write_text('{"status":"done"}\n', encoding="utf-8")

    before = acceptance.storage_manifest(books)
    status.write_text('{"status":"failed"}\n', encoding="utf-8")
    after_content_change = acceptance.storage_manifest(books)
    assert after_content_change != before

    status.write_text('{"status":"done"}\n', encoding="utf-8")
    (job / ".lock").write_text("locked\n", encoding="utf-8")
    after_structure_change = acceptance.storage_manifest(books)
    assert after_structure_change != before


def test_http_acceptance_proves_authentication_and_both_results() -> None:
    correct_key = "production-key"
    calls: list[tuple[str, str, dict[str, object] | None, str | None]] = []

    def requester(url, method, payload, api_key):
        calls.append((url, method, payload, api_key))
        if url.endswith("/health"):
            return 200, {"status": "ok"}
        if url.endswith("/ready"):
            return 200, {"ready": True}
        if url.endswith("/api/v1/status"):
            return 200, {"implemented": ["POST /api/v1/validate"]}
        if url.endswith("/api/v1/validate"):
            if api_key != correct_key:
                return 403, {"detail": "Forbidden"}
            if payload and payload.get("content") == "":
                return 200, {
                    "valid": False,
                    "errors": [{"code": "empty-manuscript"}],
                }
            return 200, {"valid": True, "errors": []}
        raise AssertionError(url)

    evidence = acceptance.run_http_acceptance(
        "https://publish.example",
        correct_key,
        requester=requester,
    )

    assert evidence["missing_key"] == 403
    assert evidence["wrong_key"] == 403
    assert evidence["valid"] is True
    assert evidence["invalid"] is False
    validation_calls = [call for call in calls if call[0].endswith("/validate")]
    assert len(validation_calls) == 4
    assert validation_calls[0][3] is None
    assert validation_calls[1][3] not in {None, correct_key}
    assert validation_calls[2][3] == correct_key
    assert validation_calls[3][3] == correct_key


def test_four_format_smoke_requires_real_file_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "templates").mkdir(parents=True)

    def fake_export(_source: Path, output_dir: Path, _log: Path) -> dict[str, str]:
        output_dir.mkdir(parents=True)
        (output_dir / "book-standard.pdf").write_bytes(b"%PDF-1.7\nstandard")
        (output_dir / "book-nd.pdf").write_bytes(b"%PDF-1.7\nnd")
        for name in ("book.epub", "book.docx"):
            with zipfile.ZipFile(output_dir / name, "w") as archive:
                archive.writestr("proof.txt", "valid")
        return {
            "pdf_standard": "book-standard.pdf",
            "pdf_nd": "book-nd.pdf",
            "epub": "book.epub",
            "docx": "book.docx",
        }

    monkeypatch.setattr(acceptance, "pandoc_export", fake_export)

    evidence = acceptance.run_four_format_smoke(repo_root)

    assert set(evidence) == {"pdf_standard", "pdf_nd", "epub", "docx"}
    assert all(item["size"] > 0 for item in evidence.values())
    assert all(len(item["sha256"]) == 64 for item in evidence.values())


def test_pinned_installer_uses_official_digest_verified_assets() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = (root / "scripts" / "install_pinned_pandoc.sh").read_text(
        encoding="utf-8"
    )

    assert 'PANDOC_VERSION="3.9.0.2"' in installer
    assert "a69abfababda8a56969a254b09f9553a7be89ddec00d4e0fe9fd585d71a67508" in installer
    assert "b6d21e8f9c3b15744f5a7ab40248019157ed7793875dbe0383d4c82ff572b528" in installer
    assert "github.com/jgm/pandoc/releases/download" in installer
    assert "--proto '=https'" in installer
    assert "sha256sum --check --strict --status" in installer
    assert "--sandbox" in installer
    assert "unsupported architecture" in installer


def test_every_installation_surface_uses_the_shared_pinned_runtime() -> None:
    root = Path(__file__).resolve().parents[1]
    install = (root / "scripts" / "install.sh").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    api_unit = (root / "deploy" / "systemd" / "book-system-api.service").read_text(
        encoding="utf-8"
    )
    worker_unit = (
        root / "deploy" / "systemd" / "book-system-worker.service"
    ).read_text(encoding="utf-8")

    assert "install_pinned_pandoc.sh" in install
    assert "apt-get install -y python3" in install
    assert "python3-pip pandoc" not in install
    assert "runuser -u www-data -- env PATH=" in install

    assert "Install exact export toolchain" in workflow
    assert "install_pinned_pandoc.sh" in workflow
    assert "apt-get install -y pandoc" not in workflow

    assert f"Environment=PATH={PINNED_RUNTIME_PATH}" in api_unit
    assert f"Environment=PATH={PINNED_RUNTIME_PATH}" in worker_unit


def test_production_launcher_bootstraps_candidate_surface_from_old_checkout(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    bash = _require_command("bash")
    repository_root = Path(__file__).resolve().parents[1]
    launcher = repository_root / "scripts" / "production_v2_01_acceptance.sh"
    fixture_root = tmp_path
    if os.name == "nt":
        fixture_root = (
            repository_root
            / ".pytest-shell-tmp"
            / f"{tmp_path.name}-{uuid.uuid4().hex}"
        )
        request.addfinalizer(lambda: shutil.rmtree(fixture_root, ignore_errors=True))
    fixture_root.mkdir(parents=True, exist_ok=True)
    repo = fixture_root / "old-production-checkout"
    trace = fixture_root / "bootstrap-trace.txt"
    work = fixture_root / "launcher-work"
    fake_bin = fixture_root / "fake-bin"
    repo.mkdir()
    work.mkdir()
    fake_bin.mkdir()

    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Tests")
    _git(repo, "checkout", "-b", "main")

    _write_script(
        repo / "scripts" / "deploy_server.sh",
        "#!/usr/bin/env bash\n"
        "echo old-deploy-ran >> \"$TRACE\"\n"
        "touch \"$REPO_ROOT_UNDER_TEST/old-deploy-marker\"\n"
        "exit 88\n",
    )
    (repo / "config").mkdir()
    (repo / "config" / "env").write_text("BOOK_API_KEY=test\n", encoding="utf-8")
    (repo / "books").mkdir()
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "old production checkout")
    old_commit = _git(repo, "rev-parse", "HEAD")

    _write_script(
        repo / "scripts" / "check_runtime_compatibility.py",
        "# candidate compatibility marker\n",
    )
    _write_script(
        repo / "scripts" / "install_pinned_pandoc.sh",
        "#!/usr/bin/env bash\n"
        "echo candidate-installer=$0 >> \"$TRACE\"\n",
    )
    _write_script(
        repo / "scripts" / "v2_01_live_acceptance.py",
        "# candidate live acceptance marker\n",
    )
    _write_script(
        repo / "scripts" / "deploy_server.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "repo_root=''\n"
        "expected=''\n"
        "while (($#)); do\n"
        "  case \"$1\" in\n"
        "    --repo-root) repo_root=\"$2\"; shift 2 ;;\n"
        "    --expected-commit) expected=\"$2\"; shift 2 ;;\n"
        "    *) echo \"unexpected argument: $1\" >&2; exit 2 ;;\n"
        "  esac\n"
        "done\n"
        "echo candidate-deploy-script=$0 >> \"$TRACE\"\n"
        "echo candidate-deploy-target=$repo_root >> \"$TRACE\"\n"
        "echo candidate-deploy-expected=$expected >> \"$TRACE\"\n"
        "[ \"$repo_root\" = \"$REPO_ROOT_UNDER_TEST\" ]\n"
        "[ \"$0\" != \"$repo_root/scripts/deploy_server.sh\" ]\n"
        "touch \"$repo_root/deploy-target-marker\"\n",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate execution surface")
    candidate_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", old_commit)
    (repo / "scripts" / "check_runtime_compatibility.py").unlink(missing_ok=True)

    _write_script(
        repo / ".venv" / "bin" / "python",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "script=\"${1:-}\"\n"
        "if [ ! -f \"$script\" ]; then\n"
        "  echo \"$0: can't open file '$script': [Errno 2] No such file or directory\" >&2\n"
        "  exit 2\n"
        "fi\n"
        "echo python-script=$script >> \"$TRACE\"\n"
        "shift\n"
        "echo python-args=$* >> \"$TRACE\"\n",
    )
    _write_script(
        fake_bin / "runuser",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "while [ \"$#\" -gt 0 ] && [ \"$1\" != \"--\" ]; do shift; done\n"
        "[ \"${1:-}\" = \"--\" ] && shift\n"
        "echo runuser-command=$* >> \"$TRACE\"\n"
        "exec \"$@\"\n",
    )
    _write_script(
        fake_bin / "install",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "directory=0\n"
        "paths=()\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -d) directory=1; shift ;;\n"
        "    -m|-o|-g) shift 2 ;;\n"
        "    *) paths+=(\"$1\"); shift ;;\n"
        "  esac\n"
        "done\n"
        "[ \"$directory\" = 1 ]\n"
        "mkdir -p \"${paths[@]}\"\n",
    )

    env = {
        **os.environ,
        "TRACE": _bash_path(bash, trace),
        "REPO_ROOT_UNDER_TEST": _bash_path(bash, repo),
        "PATH": (
            f"{_bash_path(bash, fake_bin)}:"
            f"{_bash_path(bash, Path(bash).parent)}:"
            f"/usr/bin:/bin:{os.environ['PATH']}"
        ),
    }
    old_result = _run(
        [
            bash,
            "-c",
            "./.venv/bin/python scripts/check_runtime_compatibility.py --pandoc-only",
        ],
        cwd=repo,
        env=env,
    )
    assert old_result.returncode == 2
    assert "can't open file" in old_result.stderr

    harness = (
        "set -Eeuo pipefail\n"
        f"source '{_bash_path(bash, launcher)}'\n"
        f"REPO_ROOT='{_bash_path(bash, repo)}'\n"
        f"EXPECTED_COMMIT='{candidate_commit}'\n"
        f"WORK_DIR='{_bash_path(bash, work)}'\n"
        f"CANDIDATE_TREE='{_bash_path(bash, work)}/candidate-tree'\n"
        "cd \"$REPO_ROOT\"\n"
        "stage_candidate_tree\n"
        "install_candidate_pandoc_runtime\n"
        "run_candidate_runtime_capability\n"
        "run_candidate_guarded_deployment\n"
    )
    corrected = _run([bash, "-c", harness], env=env)

    assert corrected.returncode == 0, corrected.stderr
    assert "candidate-execution-surface=" in corrected.stdout
    trace_text = trace.read_text(encoding="utf-8")
    staged_root = f"{_bash_path(bash, work)}/candidate-tree"
    assert f"candidate-installer={staged_root}/scripts/install_pinned_pandoc.sh" in trace_text
    assert f"python-script={staged_root}/scripts/check_runtime_compatibility.py" in trace_text
    assert f"candidate-deploy-script={staged_root}/scripts/deploy_server.sh" in trace_text
    assert f"candidate-deploy-target={_bash_path(bash, repo)}" in trace_text
    assert f"candidate-deploy-expected={candidate_commit}" in trace_text
    assert "runuser-command=env PATH=" in trace_text
    assert not (repo / "old-deploy-marker").exists()
    assert (repo / "deploy-target-marker").is_file()


def test_candidate_surface_is_readable_but_not_writable_by_real_www_data() -> None:
    if os.name != "posix":
        pytest.skip("real www-data service-account proof requires POSIX")
    for command in ("sudo", "bash", "runuser", "id"):
        _require_command(command)
    if _run(["id", "-u", "www-data"]).returncode != 0:
        pytest.skip("www-data user is unavailable")
    if _run(["sudo", "-n", "true"]).returncode != 0:
        pytest.skip("passwordless sudo is required for root-owned service-account proof")

    root = Path(__file__).resolve().parents[1]
    launcher = root / "scripts" / "production_v2_01_acceptance.sh"
    harness = f"""
set -Eeuo pipefail
source '{launcher.as_posix()}'
TEST_ROOT="$(mktemp -d -p /run book-system-v2b-service-proof.XXXXXXXXXX)"
trap 'rm -rf -- "$TEST_ROOT"' EXIT
chown root:www-data "$TEST_ROOT"
chmod 0750 "$TEST_ROOT"
REPO_ROOT="$TEST_ROOT/repo"
CANDIDATE_TREE="$TEST_ROOT/book-system-candidate-tree.fixture"
mkdir -p "$REPO_ROOT/.venv/bin" "$CANDIDATE_TREE/scripts" "$CANDIDATE_TREE/app/services"
cat > "$REPO_ROOT/.venv/bin/python" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
script="$1"
shift
exec python3 "$script" "$@"
SH
chmod 0755 "$REPO_ROOT/.venv/bin/python"
cat > "$CANDIDATE_TREE/scripts/check_runtime_compatibility.py" <<'PY'
from __future__ import annotations

import os
import sys
from pathlib import Path

candidate_root = Path(__file__).resolve().parents[1]
print(f"candidate-compatibility-euid={{os.geteuid()}}")
print(f"candidate-compatibility-args={{' '.join(sys.argv[1:])}}")
if os.geteuid() != 0:
    try:
        (candidate_root / "www-data-write-probe").write_text("unsafe", encoding="utf-8")
    except OSError:
        print("candidate-tree-write=blocked")
    else:
        raise SystemExit("candidate tree was writable by www-data")
PY
cat > "$CANDIDATE_TREE/app/services/pandoc_capability.py" <<'PY'
# candidate application module readability marker
PY
make_candidate_execution_surface_service_readable
verify_candidate_execution_surface_service_boundary
run_candidate_runtime_capability
if runuser -u www-data -- sh -c 'printf unsafe > "$1"/direct-write-probe' _ "$CANDIDATE_TREE"; then
  echo "direct-write=unexpected-success"
  exit 7
fi
echo "direct-write=blocked"
"""
    result = _run(["sudo", "-n", "bash", "-c", harness])

    assert result.returncode == 0, result.stderr
    assert "candidate-execution-surface-www-data-readability=pass" in result.stdout
    assert "candidate-execution-surface-www-data-nonwritable=pass" in result.stdout
    assert "candidate-compatibility-euid=0" in result.stdout
    assert "candidate-tree-write=blocked" in result.stdout
    assert "direct-write=blocked" in result.stdout
    www_data_uid = _run(["id", "-u", "www-data"]).stdout.strip()
    assert f"candidate-compatibility-euid={www_data_uid}" in result.stdout


def test_production_launcher_keeps_dangerous_operations_out_of_scope() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "production_v2_01_acceptance.sh").read_text(
        encoding="utf-8"
    )

    assert "merge_pull_request" not in launcher
    assert "git push" not in launcher
    assert "rm -rf -- \"$REPO_ROOT" not in launcher
