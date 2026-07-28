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


def _require_directory(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        _fail(
            "Git metadata directory is unavailable: "
            f"{path.name}: {type(exc).__name__}"
        )
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _fail(f"Git metadata directory is not a real directory: {path.name}")
    return metadata


def _require_regular_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        _fail(
            "Git metadata file is unavailable: "
            f"{path.name}: {type(exc).__name__}"
        )
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _fail(
            "Git metadata file is not a regular non-symlink file: "
            f"{path.name}"
        )
    return metadata


def _ref_parts(ref_name: str) -> tuple[str, ...]:
    if ref_name.startswith("/") or "\\" in ref_name:
        _fail("Git HEAD contains an unsafe ref path")
    parts = tuple(ref_name.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail("Git HEAD contains an unsafe ref path")
    return parts


def _metadata_paths(repo_root: Path) -> tuple[list[Path], list[Path]]:
    git_dir = repo_root / ".git"
    head = git_dir / "HEAD"
    _require_directory(git_dir)
    _require_regular_file(head)

    try:
        head_value = head.read_text(encoding="utf-8").strip()
    except OSError as exc:
        _fail(f"Git HEAD is unreadable: {type(exc).__name__}")

    directories = [git_dir]
    files = [head]
    if not head_value.startswith("ref:"):
        return directories, files

    ref_name = head_value.partition(":")[2].strip()
    parts = _ref_parts(ref_name)
    current = git_dir
    for part in parts[:-1]:
        current = current / part
        _require_directory(current)
        directories.append(current)

    ref_path = current / parts[-1]
    if os.path.lexists(ref_path):
        _require_regular_file(ref_path)
        files.append(ref_path)
    else:
        packed_refs = git_dir / "packed-refs"
        _require_regular_file(packed_refs)
        files.append(packed_refs)

    return directories, files


def _check_path_authority(
    path: Path,
    *,
    directory: bool,
    expected_owner_uid: int,
    expected_owner_gid: int,
) -> None:
    metadata = (
        _require_directory(path)
        if directory
        else _require_regular_file(path)
    )
    if (
        metadata.st_uid != expected_owner_uid
        or metadata.st_gid != expected_owner_gid
    ):
        _fail(f"Git metadata ownership is unexpected: {path.name}")

    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o022:
        _fail(f"Git metadata is group/world writable: {path.name}")

    required_access = os.R_OK | os.X_OK if directory else os.R_OK
    if not os.access(path, required_access):
        _fail(f"Git metadata is unreadable: {path.name}")

    if os.geteuid() != 0 and os.access(path, os.W_OK):
        _fail(f"Git metadata is writable by the service account: {path.name}")


def _check_git_metadata(
    repo_root: Path,
    *,
    fix_head_readability: bool,
    expected_commit: str,
    expected_owner_uid: int = 0,
    expected_owner_gid: int = 0,
) -> None:
    git_dir = repo_root / ".git"
    head = git_dir / "HEAD"
    _require_directory(git_dir)
    head_metadata = _require_regular_file(head)

    if fix_head_readability:
        if os.geteuid() != 0:
            _fail("Git metadata permission correction requires root")
        if head_metadata.st_uid != 0 or head_metadata.st_gid != 0:
            _fail("Git HEAD ownership is not root:root")
        head.chmod(0o644)

    directories, files = _metadata_paths(repo_root)
    for path in directories:
        _check_path_authority(
            path,
            directory=True,
            expected_owner_uid=expected_owner_uid,
            expected_owner_gid=expected_owner_gid,
        )
    for path in files:
        _check_path_authority(
            path,
            directory=False,
            expected_owner_uid=expected_owner_uid,
            expected_owner_gid=expected_owner_gid,
        )

    label = git_commit_label(repo_root)
    if label == "unknown":
        _fail("The deployed Git commit label cannot be resolved")

    expected = expected_commit.strip().lower()
    if expected:
        if len(expected) != 40 or any(
            character not in "0123456789abcdef" for character in expected
        ):
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
