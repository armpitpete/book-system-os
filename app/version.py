from __future__ import annotations

import re
from pathlib import Path

APP_VERSION = "0.1.8"

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _read_packed_ref(git_dir: Path, ref_name: str) -> str:
    packed_refs = git_dir / "packed-refs"
    try:
        lines = packed_refs.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    for line in lines:
        if not line or line.startswith(("#", "^")):
            continue
        try:
            commit, name = line.split(" ", 1)
        except ValueError:
            continue
        if name.strip() == ref_name:
            return commit.strip()
    return ""


def git_commit_label(repo_root: Path | None = None) -> str:
    """Return the checked-out short commit without spawning Git.

    The production service runs as ``www-data`` while the checkout is owned by
    another account. Reading Git metadata directly avoids Git's safe-directory
    ownership rejection and keeps the footer tied to the deployed checkout.
    """

    root = repo_root or Path(__file__).resolve().parents[1]
    git_dir = root / ".git"

    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"

    if head.startswith("ref:"):
        ref_name = head.partition(":")[2].strip()
        try:
            commit = (git_dir / ref_name).read_text(encoding="utf-8").strip()
        except OSError:
            commit = _read_packed_ref(git_dir, ref_name)
    else:
        commit = head

    if not _COMMIT_RE.fullmatch(commit):
        return "unknown"
    return commit[:7].lower()
