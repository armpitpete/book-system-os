#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class VerificationError(RuntimeError):
    """Raised when authenticated post-rollback job verification fails."""


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def authenticated_get(url: str, username: str, password: str) -> bytes:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = Request(url, headers={"Authorization": f"Basic {token}"})
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise VerificationError(f"unexpected HTTP status {response.status}")
            return response.read()
    except VerificationError:
        raise
    except Exception as exc:
        raise VerificationError(f"authenticated request failed for {urlparse(url).path}") from exc


def verify_job(
    *,
    root: Path,
    job_id: str,
    base_url: str,
    env_file: Path,
) -> dict[str, Any]:
    parsed_url = urlparse(base_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in ALLOWED_LOCAL_HOSTS:
        raise VerificationError("credentials may be sent only to a local HTTP endpoint")

    job_dir = (root / "books" / "jobs" / job_id).resolve(strict=True)
    jobs_root = (root / "books" / "jobs").resolve(strict=True)
    try:
        job_dir.relative_to(jobs_root)
    except ValueError as exc:
        raise VerificationError("job path escaped the job store") from exc

    manifest_path = job_dir / "manifest.json"
    status_path = job_dir / "status.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(status, dict):
        raise VerificationError("job records must be JSON objects")
    if status.get("status") != "done":
        raise VerificationError("post-rollback download job is not completed")

    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise VerificationError("manifest has no output declarations")

    env = load_env(env_file)
    username = env.get("BOOK_ADMIN_USERNAME", "")
    password = env.get("BOOK_ADMIN_PASSWORD", "")
    if not username or not password:
        raise VerificationError("dashboard credentials are missing")

    base = base_url.rstrip("/")
    safe_job_id = quote(job_id, safe="")
    detail = authenticated_get(f"{base}/jobs/{safe_job_id}", username, password)
    if job_id.encode("utf-8") not in detail:
        raise VerificationError("authenticated job detail did not identify the expected job")

    verified_outputs: list[dict[str, Any]] = []
    for filename in sorted(outputs.values()):
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise VerificationError("manifest contains an unsafe output filename")
        local_path = job_dir / "output" / filename
        if not local_path.is_file() or local_path.stat().st_size <= 0:
            raise VerificationError(f"local output is missing or empty: {filename}")
        payload = authenticated_get(
            f"{base}/jobs/{safe_job_id}/output/{quote(filename, safe='')}",
            username,
            password,
        )
        local_digest = sha256_file(local_path)
        download_digest = sha256_bytes(payload)
        if download_digest != local_digest:
            raise VerificationError(f"download differs from retained output: {filename}")
        verified_outputs.append(
            {
                "filename": filename,
                "bytes": len(payload),
                "sha256": download_digest,
            }
        )

    return {
        "version": 1,
        "job_id": job_id,
        "detail": "pass",
        "downloads": verified_outputs,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify authenticated job detail and downloads after rollback."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = verify_job(
            root=args.root.resolve(strict=True),
            job_id=args.job_id,
            base_url=args.base_url,
            env_file=args.env_file.resolve(strict=True),
        )
        write_report(report, args.output)
    except (OSError, ValueError, json.JSONDecodeError, VerificationError) as exc:
        raise SystemExit(f"verification-error: {exc}") from exc
    print(
        json.dumps(
            {
                "job_id": report["job_id"],
                "downloads": len(report["downloads"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
