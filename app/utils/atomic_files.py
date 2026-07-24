from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, TextIO


DEFAULT_FILE_MODE = 0o644


def _write_text_file(handle: TextIO, text: str) -> None:
    """Write one complete text payload.

    Kept as a small seam so fault-injection tests can interrupt a temporary-file
    write without touching the authoritative target.
    """

    handle.write(text)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY

    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return

    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems do not support directory fsync. The file itself has
        # already been flushed and atomically replaced at this point.
        pass
    finally:
        os.close(descriptor)


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> None:
    """Atomically create or replace a UTF-8 text file in its own directory.

    The previous final file remains authoritative until the complete temporary
    file has been flushed and ``os.replace`` succeeds. A failed first write
    leaves no final target. Temporary files are removed on every ordinary
    failure path.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    existing_mode: int | None = None
    try:
        existing_mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        pass

    final_mode = mode if mode is not None else existing_mode or DEFAULT_FILE_MODE
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)

    try:
        os.fchmod(descriptor, final_mode)
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            descriptor = -1
            _write_text_file(handle, text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
    mode: int | None = None,
) -> None:
    """Serialise JSON fully, then atomically publish it as one final record."""

    payload = json.dumps(
        value,
        indent=indent,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
    )
    atomic_write_text(path, payload, mode=mode)
