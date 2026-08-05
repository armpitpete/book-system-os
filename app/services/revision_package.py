from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from app.services.revision_studio import RevisionStudioError, get_current, revision_root

PACKAGE_VERSION = "0.1"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
README_NAME = "README.md"
MANIFEST_NAME = "manifest.json"
PAYLOAD_ROOT = "revision"


@dataclass(frozen=True, slots=True)
class RevisionPackage:
    document_id: str
    filename: str
    content: bytes
    sha256: str
    file_count: int

    def summary(self) -> dict[str, Any]:
        return {
            "package_version": PACKAGE_VERSION,
            "document_id": self.document_id,
            "filename": self.filename,
            "sha256": self.sha256,
            "bytes": len(self.content),
            "file_count": self.file_count,
        }


class RevisionPackageError(RevisionStudioError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _safe_archive_name(name: str) -> str:
    candidate = PurePosixPath(name)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or "\\" in name
    ):
        raise RevisionPackageError(
            f"Unsafe package path: {name}",
            code="unsafe-package-path",
            status_code=400,
        )
    return candidate.as_posix()


def _iter_document_files(document_dir: Path) -> Iterable[tuple[str, bytes]]:
    resolved_root = document_dir.resolve()
    for path in sorted(document_dir.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise RevisionPackageError(
                f"Revision data contains a symbolic link: {path.name}",
                code="revision-package-symlink",
                status_code=409,
            )
        if not path.is_file():
            continue
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RevisionPackageError(
                f"Revision data changed during export: {path.name}",
                code="revision-package-source-changed",
                status_code=409,
            ) from exc
        if resolved_root not in resolved.parents:
            raise RevisionPackageError(
                f"Revision data escapes its document directory: {path.name}",
                code="revision-package-path-escape",
                status_code=409,
            )
        relative = path.relative_to(document_dir).as_posix()
        archive_name = _safe_archive_name(f"{PAYLOAD_ROOT}/{relative}")
        yield archive_name, path.read_bytes()


def _readme(document_id: str, current: dict[str, Any]) -> bytes:
    title = str(current.get("title", document_id))
    return (
        f"# Portable Revision Studio package\n\n"
        f"Document: **{title}**  \n"
        f"Document ID: `{document_id}`  \n"
        f"Current version: `{current['version_id']}`  \n"
        f"Current SHA-256: `{current['content_digest']}`\n\n"
        "## What this package contains\n\n"
        "- `revision/current.json`: the accepted Current record.\n"
        "- `revision/versions/`: accepted manuscript versions.\n"
        "- `revision/proposals/`: every retained Proposed manuscript and decision.\n"
        "- `revision/history.json`: the complete decision History.\n"
        "- `manifest.json`: exact size and SHA-256 for every payload file and this README.\n\n"
        "Rejected and kept-for-later proposals remain part of the record. "
        "Nothing in this package becomes accepted merely because it is present.\n\n"
        "## Verification\n\n"
        "Verify each file against `manifest.json`. The manifest intentionally does not "
        "hash itself; the service returns a SHA-256 for the complete ZIP archive.\n"
    ).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(_safe_archive_name(name), date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def build_revision_package(
    document_id: str,
    *,
    root: Path | None = None,
) -> RevisionPackage:
    storage_root = root or revision_root()
    current = get_current(document_id, root=storage_root)
    document_dir = storage_root / str(current["document_id"])

    files: dict[str, bytes] = {}
    for name, data in _iter_document_files(document_dir):
        if name in files:
            raise RevisionPackageError(
                f"Duplicate package path: {name}",
                code="duplicate-package-path",
                status_code=409,
            )
        files[name] = data
    files[README_NAME] = _readme(str(current["document_id"]), current)

    manifest_files = [
        {"path": name, "bytes": len(data), "sha256": _sha256(data)}
        for name, data in sorted(files.items())
    ]
    manifest = {
        "package_version": PACKAGE_VERSION,
        "document_id": current["document_id"],
        "current_version_id": current["version_id"],
        "current_content_digest": current["content_digest"],
        "manifest_scope": "all archive files except manifest.json",
        "files": manifest_files,
    }
    files[MANIFEST_NAME] = _json_bytes(manifest)

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(_zip_info(name), data)

    content = output.getvalue()
    safe_document_id = str(current["document_id"])
    return RevisionPackage(
        document_id=safe_document_id,
        filename=f"{safe_document_id}-revision-package.zip",
        content=content,
        sha256=_sha256(content),
        file_count=len(files),
    )


def verify_revision_package(content: bytes) -> dict[str, Any]:
    if not content:
        raise RevisionPackageError(
            "Package content is empty.", code="empty-revision-package"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(content), mode="r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise RevisionPackageError(
            "Package is not a readable ZIP archive.",
            code="invalid-revision-package",
        ) from exc

    with archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            raise RevisionPackageError(
                "Package contains duplicate paths.",
                code="duplicate-package-path",
            )
        for member in members:
            _safe_archive_name(member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RevisionPackageError(
                    f"Package contains a symbolic link: {member.filename}",
                    code="revision-package-symlink",
                )
            if member.is_dir():
                raise RevisionPackageError(
                    f"Package contains an unexpected directory entry: {member.filename}",
                    code="unexpected-package-directory",
                )

        if README_NAME not in names or MANIFEST_NAME not in names:
            raise RevisionPackageError(
                "Package is missing README.md or manifest.json.",
                code="incomplete-revision-package",
            )
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise RevisionPackageError(
                "Package manifest is invalid.", code="invalid-package-manifest"
            ) from exc
        if not isinstance(manifest, dict) or manifest.get("package_version") != PACKAGE_VERSION:
            raise RevisionPackageError(
                "Package manifest version is not supported.",
                code="unsupported-package-version",
            )
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise RevisionPackageError(
                "Package manifest file list is invalid.",
                code="invalid-package-manifest",
            )

        expected_names = set(names) - {MANIFEST_NAME}
        recorded_names: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise RevisionPackageError(
                    "Package manifest contains an invalid entry.",
                    code="invalid-package-manifest",
                )
            path = _safe_archive_name(str(entry.get("path", "")))
            if path in recorded_names:
                raise RevisionPackageError(
                    f"Package manifest repeats a path: {path}",
                    code="duplicate-manifest-path",
                )
            recorded_names.add(path)
            if path not in expected_names:
                raise RevisionPackageError(
                    f"Package manifest refers to a missing or excluded file: {path}",
                    code="manifest-file-mismatch",
                )
            data = archive.read(path)
            if entry.get("bytes") != len(data) or entry.get("sha256") != _sha256(data):
                raise RevisionPackageError(
                    f"Package file failed verification: {path}",
                    code="package-digest-mismatch",
                )
        if recorded_names != expected_names:
            missing = sorted(expected_names - recorded_names)
            raise RevisionPackageError(
                f"Package manifest omits files: {', '.join(missing)}",
                code="manifest-file-mismatch",
            )

    return {
        "valid": True,
        "package_version": PACKAGE_VERSION,
        "document_id": manifest.get("document_id"),
        "current_version_id": manifest.get("current_version_id"),
        "current_content_digest": manifest.get("current_content_digest"),
        "archive_sha256": _sha256(content),
        "file_count": len(names),
        "verified_payload_files": len(expected_names),
    }
