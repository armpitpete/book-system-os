from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BACKUP_PREFIX = PurePosixPath("book-system-backup")
BACKUP_FORMAT = "book-system-job-store"
BACKUP_SCHEMA_VERSION = 1
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
REQUIRED_JOB_DIRECTORIES = ("input", "work", "output", "logs")
EVENT_HISTORY_REQUIRED_AT = datetime(2026, 6, 21, 10, 33, 9, tzinfo=timezone.utc)
FINAL_MANIFEST_STATUS_REQUIRED_AT = datetime(2026, 7, 19, 18, 56, 19, tzinfo=timezone.utc)
LEGACY_MANIFEST_STEP = "pandoc-export"
LEGACY_MANIFEST_MESSAGE = "Building PDF/EPUB/DOCX outputs"


class BackupValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationSummary:
    archive: str
    jobs: int
    files: int
    bytes: int
    legacy_jobs_without_events: int
    legacy_manifests_without_final_status: int
    restored_to: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "archive": self.archive,
            "jobs": self.jobs,
            "files": self.files,
            "bytes": self.bytes,
            "legacy_jobs_without_events": self.legacy_jobs_without_events,
            "legacy_manifests_without_final_status": self.legacy_manifests_without_final_status,
            "restored_to": self.restored_to,
        }


def _safe_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name:
        raise BackupValidationError(f"Unsafe archive member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise BackupValidationError(f"Unsafe archive member path: {name!r}")
    if path != BACKUP_PREFIX and BACKUP_PREFIX not in path.parents:
        raise BackupValidationError(f"Archive member is outside {BACKUP_PREFIX}: {name!r}")
    return path


def _read_member_bytes(archive: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    handle = archive.extractfile(member)
    if handle is None:
        raise BackupValidationError(f"Could not read archive member: {member.name}")
    return handle.read()


def _parse_json_object(raw: bytes, name: str) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupValidationError(f"Invalid JSON in {name}: {exc}") from exc
    if not isinstance(value, dict):
        raise BackupValidationError(f"JSON record must be an object: {name}")
    return value


def _parse_utc_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BackupValidationError(f"Timestamp is missing or invalid: {name}")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise BackupValidationError(f"Timestamp is missing or invalid: {name}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_events(raw: bytes, name: str) -> None:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BackupValidationError(f"Event history is not UTF-8: {name}") from exc
    populated = 0
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        populated += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BackupValidationError(f"Invalid event JSON in {name}:{number}: {exc}") from exc
        if not isinstance(event, dict):
            raise BackupValidationError(f"Event must be an object in {name}:{number}")
    if populated == 0:
        raise BackupValidationError(f"Event history is empty: {name}")


def _normalise_members(
    archive: tarfile.TarFile,
) -> tuple[dict[PurePosixPath, tarfile.TarInfo], int, int]:
    members: dict[PurePosixPath, tarfile.TarInfo] = {}
    file_count = 0
    byte_count = 0
    for member in archive.getmembers():
        path = _safe_member_path(member.name.rstrip("/"))
        if path in members:
            raise BackupValidationError(f"Duplicate archive member: {member.name}")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise BackupValidationError(f"Unsupported archive member type: {member.name}")
        if not member.isdir() and not member.isfile():
            raise BackupValidationError(f"Unsupported archive member type: {member.name}")
        members[path] = member
        if member.isfile():
            file_count += 1
            byte_count += member.size
    return members, file_count, byte_count


def _require_file_member(
    members: dict[PurePosixPath, tarfile.TarInfo], path: PurePosixPath
) -> tarfile.TarInfo:
    member = members.get(path)
    if member is None or not member.isfile():
        raise BackupValidationError(f"Required backup file is missing: {path}")
    return member


def _read_required_file(
    archive: tarfile.TarFile,
    members: dict[PurePosixPath, tarfile.TarInfo],
    path: PurePosixPath,
) -> bytes:
    return _read_member_bytes(archive, _require_file_member(members, path))


def _require_directory(
    members: dict[PurePosixPath, tarfile.TarInfo], path: PurePosixPath
) -> None:
    member = members.get(path)
    if member is None or not member.isdir():
        raise BackupValidationError(f"Required backup directory is missing: {path}")


def _validate_config_shape(raw: bytes) -> None:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise BackupValidationError("config/env.keys is not UTF-8") from exc
    keys = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not keys:
        raise BackupValidationError("config/env.keys contains no configuration keys")
    if len(keys) != len(set(keys)):
        raise BackupValidationError("config/env.keys contains duplicate keys")
    for key in keys:
        if "=" in key or not ENV_KEY_RE.fullmatch(key):
            raise BackupValidationError(f"config/env.keys contains a value or invalid key: {key!r}")


def _job_ids(members: dict[PurePosixPath, tarfile.TarInfo]) -> list[str]:
    root = BACKUP_PREFIX / "books" / "jobs"
    ids: set[str] = set()
    for path in members:
        if root not in path.parents:
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] != ".gitkeep":
            ids.add(relative.parts[0])
    return sorted(ids)


def _validate_manifest_outputs(
    manifest: dict[str, object],
    members: dict[PurePosixPath, tarfile.TarInfo],
    job_root: PurePosixPath,
    job_id: str,
) -> None:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise BackupValidationError(f"Completed job manifest has no outputs: {job_id}")
    for output_name in outputs.values():
        if (
            not isinstance(output_name, str)
            or not output_name
            or "/" in output_name
            or "\\" in output_name
            or PurePosixPath(output_name).name != output_name
        ):
            raise BackupValidationError(f"Unsafe manifest output name in job {job_id}")
        output_path = job_root / "output" / output_name
        output_member = members.get(output_path)
        if output_member is None or not output_member.isfile() or output_member.size <= 0:
            raise BackupValidationError(f"Manifest output is missing or empty: {output_path}")


def _validate_completed_manifest(
    manifest: dict[str, object],
    status: dict[str, object],
    members: dict[PurePosixPath, tarfile.TarInfo],
    job_root: PurePosixPath,
    job_id: str,
) -> bool:
    _validate_manifest_outputs(manifest, members, job_root, job_id)
    manifest_status = manifest.get("status")
    if isinstance(manifest_status, dict) and manifest_status.get("status") == "done":
        return False

    completed_at = _parse_utc_timestamp(
        manifest.get("completed_at"), f"{job_id}/manifest.json completed_at"
    )
    legacy_shape = (
        completed_at < FINAL_MANIFEST_STATUS_REQUIRED_AT
        and isinstance(manifest_status, dict)
        and manifest_status.get("status") == "running"
        and manifest_status.get("step") == LEGACY_MANIFEST_STEP
        and manifest_status.get("message") == LEGACY_MANIFEST_MESSAGE
    )
    if not legacy_shape:
        raise BackupValidationError(f"Completed job manifest is not final: {job_id}")

    external_state = status.get("state")
    embedded_state = manifest_status.get("state")
    if (
        isinstance(external_state, str)
        and isinstance(embedded_state, str)
        and external_state != embedded_state
    ):
        raise BackupValidationError(f"Legacy manifest state does not match final status: {job_id}")
    return True


def _validate_job(
    archive: tarfile.TarFile,
    members: dict[PurePosixPath, tarfile.TarInfo],
    job_id: str,
) -> tuple[bool, bool]:
    job_root = BACKUP_PREFIX / "books" / "jobs" / job_id
    _require_directory(members, job_root)
    for directory in REQUIRED_JOB_DIRECTORIES:
        _require_directory(members, job_root / directory)

    metadata = _parse_json_object(
        _read_required_file(archive, members, job_root / "metadata.json"),
        f"{job_id}/metadata.json",
    )
    status = _parse_json_object(
        _read_required_file(archive, members, job_root / "status.json"),
        f"{job_id}/status.json",
    )
    _require_file_member(members, job_root / "input" / "book.md")

    if metadata.get("job_id") != job_id:
        raise BackupValidationError(
            f"Job identity mismatch: directory {job_id!r}, metadata {metadata.get('job_id')!r}"
        )
    if not isinstance(status.get("status"), str) or not status.get("status"):
        raise BackupValidationError(f"Job status is missing or invalid: {job_id}")

    events_path = job_root / "events.jsonl"
    events_member = members.get(events_path)
    legacy_without_events = False
    if events_member is None:
        created_at = _parse_utc_timestamp(
            metadata.get("created_at"), f"{job_id}/metadata.json created_at"
        )
        if created_at >= EVENT_HISTORY_REQUIRED_AT:
            raise BackupValidationError(
                f"Modern job is missing required event history: {events_path}"
            )
        legacy_without_events = True
    elif not events_member.isfile():
        raise BackupValidationError(f"Event history path is not a file: {events_path}")
    else:
        _validate_events(
            _read_member_bytes(archive, events_member), f"{job_id}/events.jsonl"
        )

    manifest_path = job_root / "manifest.json"
    manifest_member = members.get(manifest_path)
    legacy_manifest = False
    if status.get("status") == "done":
        manifest = _parse_json_object(
            _read_required_file(archive, members, manifest_path),
            f"{job_id}/manifest.json",
        )
        legacy_manifest = _validate_completed_manifest(
            manifest, status, members, job_root, job_id
        )
    elif manifest_member is not None:
        if not manifest_member.isfile():
            raise BackupValidationError(f"Manifest path is not a file: {manifest_path}")
        _parse_json_object(
            _read_member_bytes(archive, manifest_member), f"{job_id}/manifest.json"
        )
    return legacy_without_events, legacy_manifest


def validate_archive(archive_path: Path) -> ValidationSummary:
    if not archive_path.is_file():
        raise BackupValidationError(f"Backup archive does not exist: {archive_path}")
    try:
        archive = tarfile.open(archive_path, mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        raise BackupValidationError(f"Backup archive cannot be opened: {exc}") from exc

    with archive:
        members, file_count, byte_count = _normalise_members(archive)
        for required in (
            BACKUP_PREFIX,
            BACKUP_PREFIX / "books",
            BACKUP_PREFIX / "books" / "jobs",
            BACKUP_PREFIX / "logs",
            BACKUP_PREFIX / "config",
        ):
            _require_directory(members, required)

        metadata = _parse_json_object(
            _read_required_file(
                archive, members, BACKUP_PREFIX / "backup-metadata.json"
            ),
            "backup-metadata.json",
        )
        if metadata.get("format") != BACKUP_FORMAT:
            raise BackupValidationError("Unknown backup format")
        if metadata.get("schema_version") != BACKUP_SCHEMA_VERSION:
            raise BackupValidationError("Unsupported backup schema version")
        if not isinstance(metadata.get("created_at"), str) or not metadata.get("created_at"):
            raise BackupValidationError("Backup metadata has no creation timestamp")

        _validate_config_shape(
            _read_required_file(
                archive, members, BACKUP_PREFIX / "config" / "env.keys"
            )
        )

        forbidden = (
            BACKUP_PREFIX / "config" / "env",
            BACKUP_PREFIX / ".env",
            BACKUP_PREFIX / "books" / "cache",
            BACKUP_PREFIX / "books" / "outputs",
        )
        for path in members:
            if path in forbidden or any(parent in forbidden for parent in path.parents):
                raise BackupValidationError(f"Forbidden backup content is present: {path}")
            if path.name == ".lock":
                raise BackupValidationError(f"Ephemeral lock file is present: {path}")

        jobs = _job_ids(members)
        compatibility = [_validate_job(archive, members, job_id) for job_id in jobs]
        legacy_jobs_without_events = sum(1 for events, _ in compatibility if events)
        legacy_manifests_without_final_status = sum(
            1 for _, manifest in compatibility if manifest
        )

    return ValidationSummary(
        archive=str(archive_path.resolve()),
        jobs=len(jobs),
        files=file_count,
        bytes=byte_count,
        legacy_jobs_without_events=legacy_jobs_without_events,
        legacy_manifests_without_final_status=legacy_manifests_without_final_status,
    )


def _ensure_empty_destination(destination: Path) -> None:
    if destination.exists():
        if not destination.is_dir():
            raise BackupValidationError(f"Restore destination is not a directory: {destination}")
        if any(destination.iterdir()):
            raise BackupValidationError(f"Restore destination is not empty: {destination}")
    else:
        destination.mkdir(parents=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _restore_member(
    archive: tarfile.TarFile, member: tarfile.TarInfo, target: Path
) -> str:
    source = archive.extractfile(member)
    if source is None:
        raise BackupValidationError(f"Could not read archive member: {member.name}")
    digest = hashlib.sha256()
    with source, target.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    target.chmod(member.mode & 0o777)
    return digest.hexdigest()


def restore_archive(archive_path: Path, destination: Path) -> ValidationSummary:
    summary = validate_archive(archive_path)
    destination = destination.resolve()
    _ensure_empty_destination(destination)
    extracted_hashes: dict[Path, str] = {}
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members, _, _ = _normalise_members(archive)
            ordered = sorted(
                members.items(), key=lambda item: (len(item[0].parts), str(item[0]))
            )
            for archive_path_key, member in ordered:
                if archive_path_key == BACKUP_PREFIX:
                    continue
                relative = archive_path_key.relative_to(BACKUP_PREFIX)
                target = destination.joinpath(*relative.parts)
                target_resolved = target.resolve(strict=False)
                if destination != target_resolved and destination not in target_resolved.parents:
                    raise BackupValidationError(
                        f"Restore path escapes destination: {archive_path_key}"
                    )
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(member.mode & 0o777)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted_hashes[target] = _restore_member(archive, member, target)

        for path, expected_hash in extracted_hashes.items():
            if _sha256_file(path) != expected_hash:
                raise BackupValidationError(f"Restored file hash mismatch: {path}")
        if (destination / "config" / "env").exists() or (destination / ".env").exists():
            raise BackupValidationError(
                "Restore unexpectedly contains usable runtime configuration"
            )
    except Exception:
        for child in list(destination.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        raise

    return ValidationSummary(
        archive=summary.archive,
        jobs=summary.jobs,
        files=summary.files,
        bytes=summary.bytes,
        legacy_jobs_without_events=summary.legacy_jobs_without_events,
        legacy_manifests_without_final_status=(
            summary.legacy_manifests_without_final_status
        ),
        restored_to=str(destination),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a Book System OS job-store backup and optionally restore it safely."
    )
    parser.add_argument("archive", type=Path, help="Path to the .tar.gz backup archive")
    parser.add_argument(
        "--restore-root",
        type=Path,
        help="Optional absent or empty destination for a clean-system restore rehearsal",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = (
            validate_archive(args.archive)
            if args.restore_root is None
            else restore_archive(args.archive, args.restore_root)
        )
    except BackupValidationError as exc:
        print(f"backup-validation=fail: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
    print("backup-validation=pass")
    if args.restore_root is not None:
        print("backup-restore=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
