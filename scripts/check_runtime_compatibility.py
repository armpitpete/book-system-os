from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.pandoc_capability import (  # noqa: E402
    PANDOC_DOCUMENTED_MINIMUM_VERSION,
    probe_pandoc_sandbox,
)
from app.version import git_commit_label  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check Book System OS runtime toolchain compatibility.",
    )
    parser.add_argument(
        "--pandoc-only",
        action="store_true",
        help="Check only the required Pandoc sandbox capability.",
    )
    parser.add_argument(
        "--fix-git-head-readability",
        action="store_true",
        help="Set .git/HEAD to root-owned mode 0644 before verifying it.",
    )
    parser.add_argument(
        "--expected-commit",
        default="",
        help="Full expected deployed commit used to verify the public label.",
    )
    return parser


def _fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def _check_pandoc() -> None:
    capability = probe_pandoc_sandbox()
    print(f"pandoc-documented-minimum={PANDOC_DOCUMENTED_MINIMUM_VERSION}")
    print(f"pandoc-capability-code={capability.code}")
    if not capability.compatible:
        _fail(capability.message)
    print("pandoc-sandbox-capability=pass")


def _metadata_files(repo_root: Path) -> list[Path]:
    git_dir = repo_root / ".git"
    head = git_dir / "HEAD"
    files = [head]

    try:
        head_value = head.read_text(encoding="utf-8").strip()
    except OSError as exc:
        _fail(f"Git HEAD is unreadable: {type(exc).__name__}")

    if not head_value.startswith("ref:"):
        return files

    ref_name = head_value.partition(":")[2].strip()
    ref_path = git_dir / ref_name
    if ref_path.exists():
        files.append(ref_path)
    else:
        packed_refs = git_dir / "packed-refs"
        if packed_refs.exists():
            files.append(packed_refs)
    return files


def _check_git_metadata(
    repo_root: Path,
    *,
    fix_head_readability: bool,
    expected_commit: str,
) -> None:
    git_dir = repo_root / ".git"
    head = git_dir / "HEAD"
    if not git_dir.is_dir() or not head.is_file():
        _fail("Git metadata is unavailable")

    if fix_head_readability:
        if os.geteuid() != 0:
            _fail("Git metadata permission correction requires root")
        metadata = head.stat()
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            _fail("Git HEAD ownership is not root:root")
        head.chmod(0o644)

    files = _metadata_files(repo_root)
    for path in files:
        metadata = path.stat()
        mode = stat.S_IMODE(metadata.st_mode)
        if mode & 0o022:
            _fail(f"Git metadata is group/world writable: {path.name}")
        if not os.access(path, os.R_OK):
            _fail(f"Git metadata is unreadable: {path.name}")
        if os.access(path, os.W_OK) and os.geteuid() != 0:
            _fail(f"Git metadata is writable by the service account: {path.name}")

    label = git_commit_label(repo_root)
    if label == "unknown":
        _fail("The deployed Git commit label cannot be resolved")

    expected = expected_commit.strip().lower()
    if expected:
        if len(expected) != 40 or any(char not in "0123456789abcdef" for char in expected):
            _fail("Expected commit must be a full lowercase SHA-1")
        if label != expected[:7]:
            _fail("The deployed Git commit label does not match the expected commit")

    print(f"git-commit-label={label}")
    print("git-metadata-readability=pass")
    print("git-metadata-nonwritable=pass")


def main() -> None:
    args = _parser().parse_args()
    _check_pandoc()
    if args.pandoc_only:
        return

    _check_git_metadata(
        REPO_ROOT,
        fix_head_readability=args.fix_git_head_readability,
        expected_commit=args.expected_commit,
    )
    print("runtime-compatibility=pass")


if __name__ == "__main__":
    main()
