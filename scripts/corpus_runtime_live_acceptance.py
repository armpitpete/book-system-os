#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_env_value(path: Path, key: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"Protected environment file is missing: {path}")
    prefix = f"{key}="
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if not value:
            raise RuntimeError(f"{key} is empty in {path}")
        return value
    raise RuntimeError(f"{key} is not configured in {path}")


def storage_manifest(root: Path) -> list[dict[str, object]]:
    if not root.exists():
        return []
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            entries.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "mode": mode,
                    "target": os.readlink(path),
                }
            )
        elif path.is_dir():
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "bytes": metadata.st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            entries.append({"path": relative, "type": "other", "mode": mode})
    return entries


def _request_json(
    url: str,
    *,
    method: str = "GET",
    api_key: str | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 30.0,
) -> tuple[int, object]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key is not None:
        headers["X-API-Key"] = api_key

    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"HTTP request failed for {url}: {exc.reason}") from exc

    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Endpoint returned non-JSON data: {url}") from exc


def _expect_status(actual: int, expected: int, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} returned HTTP {actual}; expected {expected}")


def _expect_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def _assert_service_baseline(base_url: str, label: str) -> dict[str, object]:
    base = base_url.rstrip("/")
    evidence: dict[str, object] = {}

    status, payload = _request_json(f"{base}/health")
    _expect_status(status, 200, f"{label} health")
    health = _expect_mapping(payload, f"{label} health")
    if health.get("status") != "ok":
        raise RuntimeError(f"{label} health payload was not healthy")
    evidence["health"] = health

    status, payload = _request_json(f"{base}/ready")
    _expect_status(status, 200, f"{label} readiness")
    readiness = _expect_mapping(payload, f"{label} readiness")
    if readiness.get("ready") is not True:
        raise RuntimeError(f"{label} readiness payload was not ready")
    evidence["ready"] = True

    status, payload = _request_json(f"{base}/api/v1/status")
    _expect_status(status, 200, f"{label} status")
    service_status = _expect_mapping(payload, f"{label} status")
    if service_status.get("ok") is not True:
        raise RuntimeError(f"{label} status payload was not ok")
    evidence["service"] = service_status.get("service")
    evidence["version"] = service_status.get("version")
    return evidence


def _internal_link_payload() -> dict[str, object]:
    manuscript = (
        "---\n"
        "title: Corpus Runtime Acceptance\n"
        "lang: en-GB\n"
        "---\n\n"
        "# Opening {#opening}\n\n"
        "[Valid](#opening)\n\n"
        "[Broken first](#missing-section)\n\n"
        "[Broken repeated](#missing-section)\n"
    )
    return {"title": "Corpus Runtime Acceptance", "content": manuscript}


def assert_internal_link_response(payload: object) -> dict[str, object]:
    result = _expect_mapping(payload, "authenticated validation")
    if result.get("valid") is not True or result.get("errors") != []:
        raise RuntimeError("Internal-link validation did not remain valid and error-free")
    if result.get("contract_version") != "0.2":
        raise RuntimeError("Validation contract version changed unexpectedly")

    summary = _expect_mapping(result.get("summary"), "validation summary")
    if summary.get("internal_link_count") != 3:
        raise RuntimeError("Public validation did not expose internal_link_count=3")
    if summary.get("broken_internal_link_count") != 2:
        raise RuntimeError("Public validation did not expose broken_internal_link_count=2")

    warnings = result.get("warnings")
    if not isinstance(warnings, list):
        raise RuntimeError("Validation warnings were not a list")
    broken = [
        warning
        for warning in warnings
        if isinstance(warning, dict) and warning.get("code") == "broken-internal-link"
    ]
    if len(broken) != 1:
        raise RuntimeError("Repeated unresolved links did not produce exactly one warning")
    if broken[0].get("severity") != "warning":
        raise RuntimeError("Broken internal link was not classified as a warning")
    if "#missing-section" not in str(broken[0].get("message", "")):
        raise RuntimeError("Broken-link warning did not identify the unresolved fragment")

    return {
        "valid": True,
        "internal_link_count": 3,
        "broken_internal_link_count": 2,
        "broken_warning_count": 1,
    }


def run_http_acceptance(
    *,
    public_base_url: str,
    local_base_url: str,
    api_key: str,
) -> dict[str, object]:
    evidence = {
        "public": _assert_service_baseline(public_base_url, "public"),
        "local": _assert_service_baseline(local_base_url, "local"),
    }

    validate_url = f"{public_base_url.rstrip('/')}/api/v1/validate"
    payload = _internal_link_payload()

    status, _ = _request_json(validate_url, method="POST", payload=payload)
    _expect_status(status, 403, "missing-key validation")

    status, _ = _request_json(
        validate_url,
        method="POST",
        api_key=f"{api_key}-incorrect",
        payload=payload,
    )
    _expect_status(status, 403, "wrong-key validation")

    status, response = _request_json(
        validate_url,
        method="POST",
        api_key=api_key,
        payload=payload,
    )
    _expect_status(status, 200, "authenticated internal-link validation")
    evidence["authentication"] = {
        "missing_key_status": 403,
        "wrong_key_status": 403,
        "valid_key_status": 200,
    }
    evidence["internal_links"] = assert_internal_link_response(response)
    return evidence


def _prepare_job(root: Path, manuscript: str, name: str) -> Path:
    job_dir = root / name
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def _semantic_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def _archive_reader_text(path: Path, suffixes: tuple[str, ...]) -> str:
    with zipfile.ZipFile(path) as archive:
        members = [
            archive.read(name).decode("utf-8", errors="strict")
            for name in archive.namelist()
            if name.lower().endswith(suffixes)
        ]
    if not members:
        raise RuntimeError(f"No reader document was found in {path.name}")
    return _semantic_text(re.sub(r"<[^>]+>", " ", "\n".join(members)))


def _docx_text(path: Path) -> str:
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return _semantic_text(
        " ".join(node.text or "" for node in root.findall(".//w:t", namespaces))
    )


def _pdf_text(path: Path) -> str:
    if shutil.which("mutool") is None:
        raise RuntimeError("mutool is required for Unicode PDF acceptance")
    completed = subprocess.run(
        ["mutool", "draw", "-q", "-F", "txt", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"mutool could not extract text from {path.name}: {completed.stderr}")
    return _semantic_text(completed.stdout)


def _copy_synthetic_evidence(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination, 0o700)
    for relative in (
        Path("status.json"),
        Path("manifest.json"),
        Path("logs/build.log"),
        Path("logs/error.log"),
    ):
        path = source / relative
        if path.is_file():
            target = destination / relative.name
            shutil.copy2(path, target)
            os.chmod(target, 0o600)
    output_dir = source / "output"
    if output_dir.is_dir():
        for path in output_dir.iterdir():
            if path.is_file():
                target = destination / path.name
                shutil.copy2(path, target)
                os.chmod(target, 0o600)


def run_pipeline_acceptance(
    *,
    repo_root: Path,
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    os.environ["BOOK_SYSTEM_ROOT"] = str(repo_root)
    runtime_bin = Path("/opt/book-system-runtime/pandoc/current/bin")
    if runtime_bin.is_dir():
        os.environ["PATH"] = f"{runtime_bin}:{os.environ.get('PATH', '')}"

    from app.pipeline.run_pipeline import run_pipeline
    from app.services.publish_plan import PUBLISH_OUTPUTS

    expected_outputs = {output.filename for output in PUBLISH_OUTPUTS}
    greek = "Καλημέρα κόσμε. Η γλώσσα παραμένει ορατή."
    cyrillic = "Привет, мир. Текст остаётся видимым."

    with tempfile.TemporaryDirectory(prefix="book-system-corpus-acceptance-") as temporary:
        root = Path(temporary)

        missing_job = _prepare_job(
            root,
            "# Missing local image\n\n![Missing](assets/missing-image.png)\n",
            "missing-image",
        )
        missing_result = run_pipeline(missing_job)
        if missing_result != 1:
            raise RuntimeError("Missing local image did not fail the pipeline")
        missing_status = json.loads(
            (missing_job / "status.json").read_text(encoding="utf-8")
        )
        if missing_status.get("status") != "failed":
            raise RuntimeError("Missing-image job status was not failed")
        if missing_status.get("step") != "input-validation":
            raise RuntimeError("Missing-image job did not fail at input-validation")
        if missing_status.get("failure_code") != "missing-image-file":
            raise RuntimeError("Missing-image job did not report missing-image-file")
        if any((missing_job / "output").iterdir()):
            raise RuntimeError("Missing-image job created output files")
        if (missing_job / "manifest.json").exists():
            raise RuntimeError("Missing-image job created a derivation manifest")
        if (missing_job / "logs" / "build.log").exists():
            raise RuntimeError("Missing-image job started the exporter")

        script_manuscript = (
            "---\n"
            "title: Corpus Script Acceptance\n"
            "lang: en-GB\n"
            "---\n\n"
            "# Greek and Cyrillic\n\n"
            f"GREEK-LIVE: {greek}\n\n"
            f"CYRILLIC-LIVE: {cyrillic}\n\n"
            "SCRIPT-LIVE-END\n"
        )
        script_job = _prepare_job(root, script_manuscript, "greek-cyrillic")
        if run_pipeline(script_job) != 0:
            error_log = script_job / "logs" / "error.log"
            diagnostics = (
                error_log.read_text(encoding="utf-8", errors="replace")
                if error_log.is_file()
                else "No error log"
            )
            raise RuntimeError(f"Greek/Cyrillic live build failed: {diagnostics}")

        output_dir = script_job / "output"
        actual_outputs = {path.name for path in output_dir.iterdir() if path.is_file()}
        if actual_outputs != expected_outputs:
            raise RuntimeError("Greek/Cyrillic live build did not create the four outputs")

        reader_texts = {
            "epub": _archive_reader_text(output_dir / "book.epub", (".xhtml", ".html")),
            "docx": _docx_text(output_dir / "book.docx"),
            "pdf_standard": _pdf_text(output_dir / "book-standard.pdf"),
            "pdf_nd": _pdf_text(output_dir / "book-nd.pdf"),
        }
        for label, reader in reader_texts.items():
            for sentinel in (greek, cyrillic, "SCRIPT-LIVE-END"):
                if _semantic_text(sentinel) not in reader:
                    raise RuntimeError(f"{label} did not preserve the exact script sentinel")

        build_log = (script_job / "logs" / "build.log").read_text(
            encoding="utf-8", errors="replace"
        ).lower()
        for marker in ("missing character", "fontspec error", "fatal error occurred"):
            if marker in build_log:
                raise RuntimeError(f"Greek/Cyrillic build log contains: {marker}")

        script_manifest = json.loads(
            (script_job / "manifest.json").read_text(encoding="utf-8")
        )
        output_evidence = script_manifest.get("output_evidence")
        if not isinstance(output_evidence, list) or len(output_evidence) != 4:
            raise RuntimeError("Greek/Cyrillic derivation manifest lacks four outputs")

        if evidence_dir is not None:
            _copy_synthetic_evidence(missing_job, evidence_dir / "missing-image")
            _copy_synthetic_evidence(script_job, evidence_dir / "greek-cyrillic")

        return {
            "missing_image": {
                "result": 1,
                "status": "failed",
                "step": "input-validation",
                "failure_code": "missing-image-file",
                "outputs": 0,
                "manifest_created": False,
                "export_started": False,
            },
            "greek_cyrillic": {
                "result": 0,
                "outputs": sorted(actual_outputs),
                "reader_checks": sorted(reader_texts),
                "output_evidence_count": 4,
                "build_log_clean": True,
            },
        }


def verify_repository(repo_root: Path, expected_commit: str) -> dict[str, object]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    head = git("rev-parse", "HEAD")
    if head != expected_commit:
        raise RuntimeError(f"Repository HEAD is {head}; expected {expected_commit}")
    branch = git("symbolic-ref", "--short", "HEAD")
    if branch != "main":
        raise RuntimeError(f"Repository branch is {branch}; expected main")
    porcelain = git("status", "--porcelain=v1", "--untracked-files=all")
    if porcelain:
        raise RuntimeError("Repository is not clean after live acceptance")
    return {"head": head, "branch": branch, "clean": True}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live acceptance for the bundled corpus runtime release."
    )
    parser.add_argument("--public-base-url", default="https://publish.toiletrage.co.uk")
    parser.add_argument("--local-base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--repo-root", type=Path, default=Path("/opt/book-system"))
    parser.add_argument("--env-file", type=Path, default=Path("/opt/book-system/config/env"))
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    evidence_dir = args.evidence_dir.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(evidence_dir, 0o700)

    summary_path = evidence_dir / "acceptance-summary.json"
    jobs_root = repo_root / "books" / "jobs"

    try:
        repository_before = verify_repository(repo_root, args.expected_commit)
        storage_before = storage_manifest(jobs_root)
        api_key = read_env_value(args.env_file.resolve(), "BOOK_API_KEY")

        http_evidence = run_http_acceptance(
            public_base_url=args.public_base_url,
            local_base_url=args.local_base_url,
            api_key=api_key,
        )
        pipeline_evidence = run_pipeline_acceptance(
            repo_root=repo_root,
            evidence_dir=evidence_dir / "synthetic-jobs",
        )

        storage_after = storage_manifest(jobs_root)
        if storage_after != storage_before:
            raise RuntimeError("Persistent job storage changed during live acceptance")
        repository_after = verify_repository(repo_root, args.expected_commit)

        summary: dict[str, object] = {
            "status": "PASS",
            "expected_commit": args.expected_commit,
            "repository_before": repository_before,
            "repository_after": repository_after,
            "persistent_storage_entries": len(storage_before),
            "persistent_storage_unchanged": True,
            "http": http_evidence,
            "pipeline": pipeline_evidence,
        }
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(summary_path, 0o600)
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "expected_commit": args.expected_commit,
            "error": str(exc),
        }
        summary_path.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(summary_path, 0o600)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
