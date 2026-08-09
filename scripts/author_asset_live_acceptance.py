from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AcceptanceError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run non-mutating live acceptance for Author Asset Workspace v0.1."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--public-base-url", default="https://publish.toiletrage.co.uk")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def read_env(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        fail("protected environment file is unavailable or unsafe")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def required(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        fail(f"required protected setting is unavailable: {key}")
    return value


def git_value(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"git verification failed: {type(exc).__name__}")


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return (
                response.status,
                response.read(),
                {str(k).lower(): str(v) for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            {str(k).lower(): str(v) for k, v in exc.headers.items()},
        )
    except OSError as exc:
        fail(f"request failed for {url}: {type(exc).__name__}")


def json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} did not return a JSON object: {type(exc).__name__}")
    if not isinstance(value, dict):
        fail(f"{label} did not return a JSON object")
    return value


def write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    env_file = args.env_file.absolute()
    evidence_dir = args.evidence_dir.resolve()
    expected = args.expected_commit.strip()
    if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
        fail("expected commit must be a full lowercase SHA-1")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production repository is not at the exact expected commit")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("production repository is not clean before Author Asset acceptance")

    values = read_env(env_file)
    admin_user = required(values, "BOOK_ADMIN_USERNAME")
    admin_password = required(values, "BOOK_ADMIN_PASSWORD")
    try:
        port = int(required(values, "BOOK_BIND_PORT"))
    except ValueError:
        fail("BOOK_BIND_PORT is not an integer")
    if not 1 <= port <= 65535:
        fail("BOOK_BIND_PORT is outside 1..65535")

    local = f"http://127.0.0.1:{port}"
    public = args.public_base_url.rstrip("/")
    probe_id = "f" * 32
    probe_dir = repo_root / "books" / "assets" / probe_id
    if probe_dir.exists():
        fail("reserved missing-asset probe already exists")

    evidence_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    evidence_dir.chmod(0o700)
    report: dict[str, Any] = {
        "contract": "author-asset-workspace-live-acceptance-v0.1",
        "expected_commit": expected,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "actual_book_readiness_claimed": False,
    }

    local_code, local_body, _ = request(f"{local}/api/v1/status")
    if local_code != 200:
        fail(f"local status returned HTTP {local_code}")
    local_status = json_object(local_body, "local status")
    enabled = local_status.get("routes_enabled")
    implemented = local_status.get("implemented")
    if not isinstance(enabled, list) or "author-assets" not in enabled:
        fail("author-assets is not declared enabled")
    required_routes = {
        "GET /assets",
        "POST /assets",
        "GET /assets/{asset_id}",
        "POST /assets/{asset_id}/configure",
        "GET /assets/{asset_id}/preview",
    }
    if not isinstance(implemented, list) or not required_routes.issubset(set(implemented)):
        fail("status does not declare the required Author Asset routes")
    report["checks"]["local-status-contract"] = "pass"

    public_code, public_body, _ = request(f"{public}/api/v1/status")
    if public_code != 200:
        fail(f"public status returned HTTP {public_code}")
    public_status = json_object(public_body, "public status")
    if public_status.get("routes_enabled") != enabled:
        fail("public and local route-enabled status differ")
    report["checks"]["public-status-contract"] = "pass"

    unauth_code, _, unauth_headers = request(f"{local}/assets")
    if unauth_code != 401:
        fail(f"unauthenticated Author Asset UI returned HTTP {unauth_code}, expected 401")
    if "basic" not in unauth_headers.get("www-authenticate", "").lower():
        fail("Author Asset UI 401 did not advertise Basic authentication")
    report["checks"]["ui-auth-boundary"] = "pass"

    basic_token = base64.b64encode(
        f"{admin_user}:{admin_password}".encode("utf-8")
    ).decode("ascii")
    auth_headers = {"Authorization": f"Basic {basic_token}"}
    ui_code, ui_body, _ = request(f"{local}/assets", headers=auth_headers)
    if ui_code != 200:
        fail(f"authenticated Author Asset UI returned HTTP {ui_code}")
    required_ui_markers = (
        b"Author Asset Workspace",
        b"Upload image",
        b"JPEG, PNG or WebP",
        b"not a freeform DTP canvas",
    )
    if any(marker not in ui_body for marker in required_ui_markers):
        fail("authenticated Author Asset UI is missing required workspace markers")
    report["checks"]["ui-authenticated-read"] = "pass"

    missing_code, missing_body, _ = request(
        f"{local}/assets/{probe_id}", headers=auth_headers
    )
    if missing_code != 404 or b"Author asset unavailable" not in missing_body:
        fail("authenticated missing asset did not fail closed as 404")
    if probe_dir.exists():
        fail("read-only missing-asset probe created persistent state")
    report["checks"]["missing-asset-read"] = "pass"
    report["checks"]["read-no-probe-state"] = "pass"

    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production commit changed during Author Asset acceptance")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("Author Asset acceptance left repository changes")
    if probe_dir.exists():
        fail("Author Asset acceptance left probe state")
    report["checks"]["repository-remained-clean"] = "pass"

    report["status"] = "PASS"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_private(
        evidence_dir / "author-asset-live-acceptance.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    write_private(
        evidence_dir / "result.txt",
        "\n".join(
            [
                "PASS",
                f"expected_commit={expected}",
                "author_asset_workspace_v0_1_live_acceptance=pass",
                "repository_remained_clean=true",
                "actual_book_readiness_claimed=false",
                "",
            ]
        ),
    )
    print("AUTHOR ASSET WORKSPACE V0.1 LIVE ACCEPTANCE — PASS")
    print(f"expected-commit={expected}")
    print(f"evidence={evidence_dir}")
    print("actual-book-readiness-claimed=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
