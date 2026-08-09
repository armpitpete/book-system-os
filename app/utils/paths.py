from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Return the configured Book System root.

    Defaults to the current working directory for local development.
    On the Oracle server this should normally be /opt/book-system.
    """

    return Path(os.getenv("BOOK_SYSTEM_ROOT", Path.cwd())).resolve()


def code_root() -> Path:
    """Return the installed source tree containing app/, filters/ and scripts/."""

    return Path(__file__).resolve().parents[2]


def jobs_dir() -> Path:
    path = repo_root() / "books" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def author_assets_dir() -> Path:
    path = repo_root() / "books" / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = repo_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def templates_dir() -> Path:
    return repo_root() / "templates"


def filters_dir() -> Path:
    # Rendering filters are versioned executable source, not mutable job data.
    # Resolve them from the installed code tree so test/storage roots cannot
    # redirect production rendering semantics.
    return code_root() / "filters"
