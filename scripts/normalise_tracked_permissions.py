#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class PermissionNormalisationError(RuntimeError):
    """Raised when Git-index permissions cannot be applied safely."""


@dataclass(frozen=True)
class TrackedEntry:
    mode: str
    stage: str
    relative_path: PurePosixPath


def _git_index_entries(root: Path) -> list[TrackedEntry]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--stage", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PermissionNormalisationError(
            f"Could not read the Git index for {root}"
        ) from exc

    entries: list[TrackedEntry] = []

    for raw_record in result.stdout.split(b"\0"):
        if not raw_record:
            continue

        try:
            raw_metadata, raw_path = raw_record.split(b"\t", 1)
            raw_mode, _raw_object, raw_stage = raw_metadata.split(b" ", 2)
            mode = raw_mode.decode("ascii")
            stage = raw_stage.decode("ascii")
            path_text = raw_path.decode("utf-8", errors="surrogateescape")
        except (ValueError, UnicodeDecodeError) as exc:
            raise PermissionNormalisationError(
                "Git returned an invalid index record"
            ) from exc

        relative = PurePosixPath(path_text)

        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
        ):
            raise PermissionNormalisationError(
                f"Unsafe tracked path in Git index: {path_text!r}"
            )

        if stage != "0":
            raise PermissionNormalisationError(
                f"Unmerged Git index entry cannot be normalised: {path_text}"
            )

        entries.append(
            TrackedEntry(
                mode=mode,
                stage=stage,
                relative_path=relative,
            )
        )

    return entries


def _tracked_path(root: Path, relative: PurePosixPath) -> Path:
    return root.joinpath(*relative.parts)


def _normalise_parent_directories(root: Path, target: Path) -> set[Path]:
    changed: set[Path] = set()
    current = target.parent

    while current != root:
        if root not in current.parents:
            raise PermissionNormalisationError(
                f"Tracked path escapes repository root: {target}"
            )
        if current.is_symlink():
            raise PermissionNormalisationError(
                f"Tracked parent directory is a symbolic link: {current}"
            )
        if not current.is_dir():
            raise PermissionNormalisationError(
                f"Tracked parent directory is missing: {current}"
            )

        current.chmod(0o755)
        changed.add(current)
        current = current.parent

    return changed


def normalise_tracked_permissions(root: Path) -> dict[str, int]:
    repository = root.resolve()

    if not (repository / ".git").exists():
        raise PermissionNormalisationError(
            f"Not a Git working tree: {repository}"
        )

    file_count = 0
    executable_count = 0
    symlink_count = 0
    gitlink_count = 0
    directories: set[Path] = set()

    for entry in _git_index_entries(repository):
        target = _tracked_path(repository, entry.relative_path)
        directories.update(
            _normalise_parent_directories(repository, target)
        )

        if entry.mode == "120000":
            if not target.is_symlink():
                raise PermissionNormalisationError(
                    f"Tracked symbolic link is missing: {entry.relative_path}"
                )
            symlink_count += 1
            continue

        if entry.mode == "160000":
            if not target.is_dir():
                raise PermissionNormalisationError(
                    f"Tracked gitlink is missing: {entry.relative_path}"
                )
            gitlink_count += 1
            continue

        if entry.mode not in {"100644", "100755"}:
            raise PermissionNormalisationError(
                f"Unsupported Git mode {entry.mode}: {entry.relative_path}"
            )

        if target.is_symlink() or not target.is_file():
            raise PermissionNormalisationError(
                f"Tracked regular file is missing or unsafe: {entry.relative_path}"
            )

        final_mode = 0o755 if entry.mode == "100755" else 0o644
        os.chmod(target, final_mode, follow_symlinks=False)
        file_count += 1

        if final_mode == 0o755:
            executable_count += 1

    return {
        "files": file_count,
        "executables": executable_count,
        "directories": len(directories),
        "symlinks": symlink_count,
        "gitlinks": gitlink_count,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Restore Git-index-authoritative permissions for tracked files "
            "without changing untracked runtime configuration."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Git working-tree root; defaults to the current directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        summary = normalise_tracked_permissions(args.root)
    except PermissionNormalisationError as exc:
        print(f"tracked-permissions=fail: {exc}", file=sys.stderr)
        return 1

    print(
        "tracked-permissions=pass "
        f"files={summary['files']} "
        f"executables={summary['executables']} "
        f"directories={summary['directories']} "
        f"symlinks={summary['symlinks']} "
        f"gitlinks={summary['gitlinks']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
