from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run non-mutating live acceptance for the current Book System OS delta."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument(
        "--public-base-url", default="https://publish.toiletrage.co.uk"
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise AcceptanceError(message)


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"protected environment file is unavailable: {path}")
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


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers.items())
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


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    env_file = args.env_file.resolve()
    evidence_dir = args.evidence_dir.resolve()
    expected = args.expected_commit.strip()
    if len(expected) != 40 or any(c not in "0123456789abcdef" for c in expected):
        fail("expected commit must be a full lowercase SHA-1")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production repository is not at the exact expected commit")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("production repository is not clean before current-delta acceptance")

    values = read_env(env_file)
    api_key = required(values, "BOOK_API_KEY")
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
    probe_id = f"bos-release-probe-missing-{expected[:12]}"
    probe_dir = repo_root / "books" / "revisions" / probe_id
    if probe_dir.exists():
        fail("reserved missing-document probe already exists")

    report: dict[str, Any] = {
        "expected_commit": expected,
        "probe_id": probe_id,
        "checks": {},
    }

    status_code, body, _ = request(f"{local}/api/v1/status")
    if status_code != 200:
        fail(f"local status returned HTTP {status_code}")
    status = json_object(body, "local status")
    routes_enabled = status.get("routes_enabled")
    implemented = status.get("implemented")
    if not isinstance(routes_enabled, list) or "revision-studio" not in routes_enabled:
        fail("revision-studio is not declared enabled")
    required_routes = {
        "GET /revisions",
        "GET /api/v1/revisions/documents/{document_id}",
        "GET /api/v1/revisions/documents/{document_id}/package",
        "POST /api/v1/revisions/package/verify",
    }
    if not isinstance(implemented, list) or not required_routes.issubset(set(implemented)):
        fail("current status does not declare the required Revision Studio routes")
    report["checks"]["local-status-contract"] = "pass"

    public_code, public_body, _ = request(f"{public}/api/v1/status")
    if public_code != 200:
        fail(f"public status returned HTTP {public_code}")
    public_status = json_object(public_body, "public status")
    if public_status.get("routes_enabled") != routes_enabled:
        fail("public and local route-enabled status differ")
    report["checks"]["public-status-contract"] = "pass"

    unauth_api, _, _ = request(
        f"{local}/api/v1/revisions/documents/{probe_id}"
    )
    if unauth_api != 403:
        fail(f"unauthenticated Revision Studio API returned HTTP {unauth_api}, expected 403")
    report["checks"]["revision-api-auth-boundary"] = "pass"

    unauth_ui, _, unauth_ui_headers = request(f"{local}/revisions")
    if unauth_ui != 401:
        fail(f"unauthenticated Revision Studio UI returned HTTP {unauth_ui}, expected 401")
    if "basic" not in unauth_ui_headers.get("WWW-Authenticate", "").lower():
        fail("Revision Studio UI 401 did not advertise Basic authentication")
    report["checks"]["revision-ui-auth-boundary"] = "pass"

    api_headers = {"X-API-Key": api_key}
    missing_code, missing_body, _ = request(
        f"{local}/api/v1/revisions/documents/{probe_id}", headers=api_headers
    )
    missing_payload = json_object(missing_body, "missing revision document")
    if missing_code != 404 or missing_payload.get("error") != "not-found":
        fail("authenticated missing revision document did not fail closed as not-found")
    report["checks"]["revision-missing-read"] = "pass"

    package_code, package_body, _ = request(
        f"{local}/api/v1/revisions/documents/{probe_id}/package", headers=api_headers
    )
    package_payload = json_object(package_body, "missing revision package")
    if package_code != 404 or package_payload.get("error") != "not-found":
        fail("authenticated missing revision package did not fail closed as not-found")
    report["checks"]["revision-missing-package"] = "pass"

    basic_token = base64.b64encode(
        f"{admin_user}:{admin_password}".encode("utf-8")
    ).decode("ascii")
    ui_code, ui_body, _ = request(
        f"{local}/revisions",
        headers={"Authorization": f"Basic {basic_token}"},
    )
    if ui_code != 200 or b"Revision Studio" not in ui_body:
        fail("authenticated Revision Studio UI did not render successfully")
    report["checks"]["revision-ui-authenticated-read"] = "pass"

    if probe_dir.exists():
        fail("read-only Revision Studio probes created persistent document state")
    report["checks"]["revision-read-no-probe-state"] = "pass"

    sys.path.insert(0, str(repo_root))
    try:
        from app.services import artifact_readiness as readiness
    except Exception as exc:  # pragma: no cover - production evidence path
        fail(f"BOS-RDY-001 import failed: {type(exc).__name__}")

    if readiness.CONTRACT != "BOS-RDY-001":
        fail("BOS-RDY-001 contract identifier differs")
    if readiness.SCHEMA_VERSION != "1":
        fail("BOS-RDY-001 schema version differs")
    if readiness.ARTIFACT_CONTRACT_VERSION != "1":
        fail("BOS-RDY-001 artifact contract version differs")
    if tuple(readiness.READINESS_CLASSES) != (
        "story-ready",
        "production-valid",
        "digital-publication-ready",
        "print-ready",
    ):
        fail("BOS-RDY-001 readiness classes differ")
    if "epub" in readiness.READINESS_ARTIFACT_MATRIX["print-ready"]:
        fail("EPUB is incorrectly allowed for print-ready")
    if "docx" not in readiness.READINESS_ARTIFACT_MATRIX["production-valid"]:
        fail("DOCX is not production-valid")
    if "docx" in readiness.READINESS_ARTIFACT_MATRIX["digital-publication-ready"]:
        fail("DOCX is incorrectly digital-publication-ready")
    if "docx" in readiness.READINESS_ARTIFACT_MATRIX["print-ready"]:
        fail("DOCX is incorrectly print-ready")
    unevaluated = readiness.unevaluated_readiness_report()
    if unevaluated.get("evaluated") is not False:
        fail("unevaluated BOS-RDY-001 report is not explicitly unevaluated")
    states = unevaluated.get("states")
    if not isinstance(states, dict) or set(states) != set(readiness.READINESS_CLASSES):
        fail("unevaluated BOS-RDY-001 state set differs")
    if any(
        not isinstance(state, dict) or state.get("ready") is not False
        for state in states.values()
    ):
        fail("unevaluated BOS-RDY-001 report did not fail closed")
    report["checks"]["bos-rdy-001-deployed-contract"] = "pass"
    report["actual_book_readiness_claimed"] = False

    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production commit changed during current-delta acceptance")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("current-delta acceptance left repository changes")
    report["checks"]["repository-remained-clean"] = "pass"

    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "current-main-live-acceptance.json"
    evidence_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(evidence_path, 0o600)
    os.chmod(evidence_dir, 0o700)

    print("current-main-live-acceptance=pass")
    print(f"expected-commit={expected}")
    print("revision-studio-live=pass")
    print("bos-rdy-001-contract-smoke=pass")
    print("actual-book-readiness-claimed=false")
    print(f"evidence={evidence_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(f"current-main-live-acceptance=fail: {exc}", file=sys.stderr)
        raise SystemExit(1)
