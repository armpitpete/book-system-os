from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.pipeline.exporters import pandoc_export  # noqa: E402
from app.pipeline.structural import structural_cleanup  # noqa: E402

HTTP_TIMEOUT_SECONDS = 30.0
VALID_MANUSCRIPT = (
    "---\n"
    "title: V2-01 live acceptance\n"
    "lang: en-GB\n"
    "---\n\n"
    "# V2-01 live acceptance\n\n"
    "A controlled manuscript proves the production validation path.\n"
)
FOUR_FORMAT_MANUSCRIPT = (
    "---\n"
    "title: Four-format production proof\n"
    "author: Book System OS\n"
    "lang: en-GB\n"
    "---\n\n"
    "# Four-format production proof\n\n"
    "This temporary manuscript verifies both PDFs, EPUB and DOCX.\n"
)

JsonRequester = Callable[[str, str, dict[str, object] | None, str | None], tuple[int, Any]]


def _fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run authenticated V2-01 production acceptance without persistent side effects.",
    )
    parser.add_argument("--base-url", default="https://publish.toiletrage.co.uk")
    parser.add_argument("--repo-root", default="/opt/book-system")
    parser.add_argument("--env-file", default="/opt/book-system/config/env")
    parser.add_argument("--expected-commit", required=True)
    return parser


def read_env_value(path: Path, key: str) -> str:
    """Read one simple KEY=VALUE entry without executing the environment file."""

    found: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        _fail(f"could not read protected environment file: {type(exc).__name__}")

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        found.append(value)

    if len(found) != 1 or not found[0]:
        _fail(f"{key} must appear exactly once with a non-empty value")
    return found[0]


def _path_record(path: Path, relative: str) -> dict[str, object]:
    metadata = path.lstat()
    record: dict[str, object] = {
        "path": relative,
        "mode": stat.S_IMODE(metadata.st_mode),
    }
    if stat.S_ISDIR(metadata.st_mode):
        record["type"] = "directory"
    elif stat.S_ISREG(metadata.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        record.update(
            type="file",
            size=metadata.st_size,
            sha256=digest.hexdigest(),
        )
    elif stat.S_ISLNK(metadata.st_mode):
        record.update(type="symlink", target=os.readlink(path))
    else:
        record["type"] = "other"
    return record


def storage_manifest(root: Path) -> list[dict[str, object]]:
    """Create a stable content and structure manifest without following symlinks."""

    if not root.exists():
        return []
    if not root.is_dir() or root.is_symlink():
        _fail(f"persistent storage root is not a real directory: {root}")

    records = [_path_record(root, ".")]
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as exc:
            _fail(f"could not inspect persistent storage: {type(exc).__name__}")
        directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            records.append(_path_record(path, relative))
            if entry.is_dir(follow_symlinks=False):
                directories.append(path)
        stack.extend(reversed(directories))
    return records


def request_json(
    url: str,
    method: str,
    payload: dict[str, object] | None,
    api_key: str | None,
) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key is not None:
        headers["x-api-key"] = api_key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    except OSError as exc:
        _fail(f"HTTP request failed for {url}: {type(exc).__name__}")
    else:
        status = response.status
        body = response.read()
        response.close()

    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(f"endpoint did not return JSON: {url} status={status}")
    return status, decoded


def _expect_status(label: str, actual: int, expected: int) -> None:
    if actual != expected:
        _fail(f"{label} returned HTTP {actual}; expected {expected}")


def run_http_acceptance(
    base_url: str,
    api_key: str,
    requester: JsonRequester = request_json,
) -> dict[str, object]:
    base = base_url.rstrip("/")

    health_status, _health = requester(f"{base}/health", "GET", None, None)
    _expect_status("public health", health_status, 200)

    ready_status, ready = requester(f"{base}/ready", "GET", None, None)
    _expect_status("public readiness", ready_status, 200)
    if not isinstance(ready, dict) or ready.get("ready") is not True:
        _fail("public readiness did not report ready=true")

    status_code, service_status = requester(f"{base}/api/v1/status", "GET", None, None)
    _expect_status("public status", status_code, 200)
    implemented = service_status.get("implemented") if isinstance(service_status, dict) else None
    if not isinstance(implemented, list) or "POST /api/v1/validate" not in implemented:
        _fail("public status does not report the validation route as implemented")

    valid_payload = {"title": "V2-01 live acceptance", "content": VALID_MANUSCRIPT}
    missing_status, _ = requester(
        f"{base}/api/v1/validate", "POST", valid_payload, None
    )
    _expect_status("missing API key", missing_status, 403)

    wrong_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    if wrong_key == api_key:
        wrong_key += "-wrong"
    wrong_status, _ = requester(
        f"{base}/api/v1/validate", "POST", valid_payload, wrong_key
    )
    _expect_status("wrong API key", wrong_status, 403)

    valid_status, valid = requester(
        f"{base}/api/v1/validate", "POST", valid_payload, api_key
    )
    _expect_status("valid manuscript", valid_status, 200)
    if not isinstance(valid, dict) or valid.get("valid") is not True:
        _fail("valid manuscript was not accepted as valid")
    if valid.get("errors") != []:
        _fail("valid manuscript returned validation errors")

    invalid_status, invalid = requester(
        f"{base}/api/v1/validate",
        "POST",
        {"title": "Invalid manuscript", "content": ""},
        api_key,
    )
    _expect_status("invalid manuscript", invalid_status, 200)
    if not isinstance(invalid, dict) or invalid.get("valid") is not False:
        _fail("invalid manuscript was not returned as valid=false")
    errors = invalid.get("errors")
    if not isinstance(errors, list) or not errors:
        _fail("invalid manuscript returned no coded validation error")

    return {
        "health": "pass",
        "readiness": "pass",
        "status": "pass",
        "missing_key": 403,
        "wrong_key": 403,
        "valid": True,
        "invalid": False,
    }


def run_four_format_smoke(repo_root: Path) -> dict[str, dict[str, object]]:
    """Build all four formats in a temporary directory outside retained storage."""

    os.environ["BOOK_SYSTEM_ROOT"] = str(repo_root)
    with tempfile.TemporaryDirectory(prefix="book-system-v2-01-") as temp_name:
        job_dir = Path(temp_name)
        work_dir = job_dir / "work"
        output_dir = job_dir / "output"
        log_file = job_dir / "logs" / "build.log"
        work_dir.mkdir(parents=True)
        source = work_dir / "book-clean.md"
        source.write_text(structural_cleanup(FOUR_FORMAT_MANUSCRIPT), encoding="utf-8")

        outputs = pandoc_export(source, output_dir, log_file)
        expected = {"pdf_standard", "pdf_nd", "epub", "docx"}
        if set(outputs) != expected:
            _fail(f"four-format smoke returned unexpected outputs: {sorted(outputs)}")

        evidence: dict[str, dict[str, object]] = {}
        for output_type, filename in sorted(outputs.items()):
            path = output_dir / filename
            if not path.is_file() or path.stat().st_size <= 0:
                _fail(f"four-format smoke produced an empty or missing {output_type}")
            data = path.read_bytes()
            if output_type.startswith("pdf_"):
                if not data.startswith(b"%PDF-"):
                    _fail(f"{output_type} does not have a PDF signature")
            else:
                try:
                    with zipfile.ZipFile(path) as archive:
                        damaged = archive.testzip()
                except zipfile.BadZipFile:
                    _fail(f"{output_type} is not a valid ZIP-based publication file")
                if damaged is not None:
                    _fail(f"{output_type} contains a damaged archive member: {damaged}")
            evidence[output_type] = {
                "filename": filename,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        return evidence


def _verify_repository(repo_root: Path, expected_commit: str) -> None:
    if len(expected_commit) != 40 or any(char not in "0123456789abcdef" for char in expected_commit):
        _fail("expected commit must be a full lowercase SHA-1")
    actual = subprocess.check_output(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    if actual != expected_commit:
        _fail(f"production checkout is {actual}; expected {expected_commit}")
    dirty = subprocess.check_output(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
        text=True,
    )
    if dirty:
        _fail("production checkout is not clean after deployment")


def main() -> int:
    args = _parser().parse_args()
    repo_root = Path(args.repo_root).resolve(strict=True)
    env_file = Path(args.env_file).resolve(strict=True)
    _verify_repository(repo_root, args.expected_commit)

    api_key = read_env_value(env_file, "BOOK_API_KEY")
    books_root = repo_root / "books"
    before = storage_manifest(books_root)

    http_evidence = run_http_acceptance(args.base_url, api_key)
    export_evidence = run_four_format_smoke(repo_root)

    after = storage_manifest(books_root)
    if after != before:
        _fail("validation or temporary export changed persistent book storage")

    _verify_repository(repo_root, args.expected_commit)
    evidence = {
        "acceptance": "pass",
        "expected_commit": args.expected_commit,
        "persistent_book_storage": "unchanged",
        "http": http_evidence,
        "four_format": export_evidence,
    }
    print(json.dumps(evidence, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
