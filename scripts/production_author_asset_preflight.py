from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Sequence

MAX_TOTAL_STORAGE_DEFAULT = 10 * 1024 * 1024 * 1024


class AssetPreflightError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AssetPreflightError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_tree(root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    byte_count = 0
    if not root.exists():
        payload = b"[]\n"
        return {"digest": hashlib.sha256(payload).hexdigest(), "entries": 0, "bytes": 0}
    if root.is_symlink() or not root.is_dir():
        fail(f"unsafe persistent-state root: {root}")

    for current_raw, dirs, files in os.walk(root, followlinks=False):
        current = Path(current_raw)
        dirs.sort()
        files.sort()
        for name in dirs:
            path = current / name
            if path.is_symlink():
                fail(f"persistent-state symlink is not allowed: {path}")
            st = path.stat()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "directory",
                    "mode": stat.S_IMODE(st.st_mode),
                }
            )
        for name in files:
            if name == ".gitkeep":
                continue
            path = current / name
            if path.is_symlink() or not path.is_file():
                fail(f"unsafe persistent-state entry: {path}")
            st = path.stat()
            byte_count += st.st_size
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "type": "file",
                    "mode": stat.S_IMODE(st.st_mode),
                    "bytes": st.st_size,
                    "sha256": sha256_file(path),
                }
            )
    payload = (json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {
        "digest": hashlib.sha256(payload).hexdigest(),
        "entries": len(records),
        "bytes": byte_count,
    }


def tree_bytes(root: Path) -> int:
    return int(snapshot_tree(root)["bytes"])


def selected_max_total_storage(env_file: Path) -> tuple[int, str]:
    if env_file.is_symlink() or not env_file.is_file():
        fail("protected environment file is unavailable or unsafe")
    raw_value: str | None = None
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "BOOK_MAX_TOTAL_STORAGE_BYTES":
            raw_value = value.strip().strip('"').strip("'")
            break
    if raw_value is None:
        return MAX_TOTAL_STORAGE_DEFAULT, "runtime-default"
    try:
        value = int(raw_value)
    except ValueError:
        fail("BOOK_MAX_TOTAL_STORAGE_BYTES is not an integer")
    if value <= 0:
        fail("BOOK_MAX_TOTAL_STORAGE_BYTES must be positive")
    return value, "config"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("/opt/book-system"))
    parser.add_argument("--env-file", type=Path, default=Path("/opt/book-system/config/env"))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path)
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    assets_root = repo_root / "books" / "assets"
    jobs_root = repo_root / "books" / "jobs"
    observed = snapshot_tree(assets_root)
    maximum, source = selected_max_total_storage(args.env_file.absolute())
    combined = tree_bytes(jobs_root) + int(observed["bytes"])
    if combined > maximum:
        fail("retained jobs and author assets exceed configured total storage limit")

    if args.phase == "before":
        write_json(
            args.snapshot,
            {
                "author_assets": observed,
                "combined_retained_bytes": combined,
                "maximum_retained_bytes": maximum,
                "maximum_retained_bytes_source": source,
            },
        )
        return 0

    if not args.snapshot.is_file():
        fail("author-asset preflight baseline is unavailable")
    try:
        before = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"author-asset preflight baseline is invalid: {type(exc).__name__}")
    if not isinstance(before, dict) or before.get("author_assets") != observed:
        fail("Author Asset Workspace persistent state changed during preflight")

    result = {
        "status": "PASS",
        "author_assets": observed,
        "combined_retained_bytes": combined,
        "maximum_retained_bytes": maximum,
        "maximum_retained_bytes_source": source,
        "author_asset_persistent_state_unchanged": True,
    }
    if args.evidence_dir:
        evidence_dir = args.evidence_dir.resolve()
        if not evidence_dir.is_dir():
            fail("base preflight evidence directory is unavailable")
        write_json(evidence_dir / "author-assets-preflight.json", result)
        result_path = evidence_dir / "result.txt"
        if result_path.is_file():
            with result_path.open("a", encoding="utf-8") as handle:
                handle.write("author_asset_persistent_state_unchanged=true\n")
            result_path.chmod(0o600)

    print("author-asset-persistent-state-unchanged=true")
    print(f"author-assets-digest={observed['digest']}")
    print(f"author-assets-bytes={observed['bytes']}")
    print(f"combined-retained-bytes={combined}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssetPreflightError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
