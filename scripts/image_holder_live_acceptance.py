from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AcceptanceError(message)


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


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"absent\0")
        return digest.hexdigest()
    if root.is_symlink() or not root.is_dir():
        fail(f"persistent root is not a safe directory: {root.name}")
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode(
            "utf-8", errors="surrogateescape"
        )
        metadata = path.lstat()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(stat.S_IMODE(metadata.st_mode)).encode("ascii"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_dir():
            digest.update(b"directory\0")
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"other\0")
        digest.update(b"\0")
    return digest.hexdigest()


def check_image_holder_runtime(repo_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repo_root))
    try:
        import PIL
        from PIL import Image
        from app.pipeline.input_validation import (
            ManuscriptInputError,
            validate_local_image_files,
        )
    except Exception as exc:
        fail(f"image-holder runtime import failed: {type(exc).__name__}")

    if PIL.__version__ != "12.3.0":
        fail(f"unexpected Pillow runtime version: {PIL.__version__}")

    with tempfile.TemporaryDirectory(prefix="book-system-image-holder-smoke-") as raw:
        root = Path(raw)
        safe = root / "safe.png"
        low = root / "low.png"
        Image.new("RGB", (2400, 1600), "white").save(safe, format="PNG")
        Image.new("RGB", (600, 400), "white").save(low, format="PNG")

        validate_local_image_files(
            '![Representative image](safe.png){holder=feature caption="Representative image."}\n',
            source_dir=root,
        )

        try:
            validate_local_image_files(
                "![Low resolution](low.png){holder=inline}\n",
                source_dir=root,
            )
        except ManuscriptInputError as exc:
            if exc.code != "image-resolution-too-low":
                fail(f"low-resolution holder failed with unexpected code: {exc.code}")
        else:
            fail("low-resolution holder input did not fail closed")

        try:
            validate_local_image_files(
                "![Remote](https://example.invalid/image.png){holder=inline}\n",
                source_dir=root,
            )
        except ManuscriptInputError as exc:
            if exc.code != "image-holder-requires-local-file":
                fail(f"remote holder failed with unexpected code: {exc.code}")
        else:
            fail("remote holder input did not fail closed")

    return {
        "pillow_version": PIL.__version__,
        "representative_holder": "pass",
        "low_resolution_fail_closed": "pass",
        "remote_holder_fail_closed": "pass",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run non-mutating production smoke checks for image-holder v0.1."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    expected = args.expected_commit.strip()
    evidence_dir = args.evidence_dir.resolve()

    if len(expected) != 40 or any(c not in "0123456789abcdef" for c in expected):
        fail("expected commit must be a full lowercase SHA-1")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production repository is not at the exact expected commit")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("production repository is not clean before image-holder acceptance")

    jobs_root = repo_root / "books" / "jobs"
    revisions_root = repo_root / "books" / "revisions"
    jobs_before = _tree_digest(jobs_root)
    revisions_before = _tree_digest(revisions_root)

    checks = check_image_holder_runtime(repo_root)

    if _tree_digest(jobs_root) != jobs_before:
        fail("image-holder acceptance changed retained job state")
    if _tree_digest(revisions_root) != revisions_before:
        fail("image-holder acceptance changed Revision Studio state")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production commit changed during image-holder acceptance")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("image-holder acceptance left repository changes")

    report = {
        "expected_commit": expected,
        "checks": checks,
        "retained_jobs_unchanged": True,
        "revision_state_unchanged": True,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "image-holder-live-acceptance.json"
    evidence_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(evidence_path, 0o600)
    os.chmod(evidence_dir, 0o700)

    print("image-holder-live-acceptance=pass")
    print(f"expected-commit={expected}")
    print("pillow-version=12.3.0")
    print("representative-holder=pass")
    print("low-resolution-fail-closed=pass")
    print("remote-holder-fail-closed=pass")
    print("retained-book-state-unchanged=true")
    print(f"evidence={evidence_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(f"image-holder-live-acceptance=fail: {exc}", file=sys.stderr)
        raise SystemExit(1)
