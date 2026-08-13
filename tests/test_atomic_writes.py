from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from app.pipeline import run_pipeline
from app.services import job_queue
from app.utils import atomic_files


def temporary_files(path: Path) -> list[Path]:
    return list(path.parent.glob(f".{path.name}.*.tmp"))


def test_atomic_json_creates_replaces_and_preserves_mode(tmp_path: Path) -> None:
    target = tmp_path / "status.json"

    atomic_files.atomic_write_json(target, {"status": "queued"})
    target.chmod(0o640)
    atomic_files.atomic_write_json(target, {"status": "done", "count": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "status": "done",
        "count": 2,
    }
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert temporary_files(target) == []


def test_replace_failure_leaves_previous_json_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "metadata.json"
    original = '{"job_id": "original"}'
    target.write_text(original, encoding="utf-8")

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replacement failure"):
        atomic_files.atomic_write_json(target, {"job_id": "replacement"})

    assert target.read_text(encoding="utf-8") == original
    assert json.loads(target.read_text(encoding="utf-8"))["job_id"] == "original"
    assert temporary_files(target) == []


def test_partial_temporary_write_never_corrupts_final_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "manifest.json"
    original = '{"status": {"status": "done"}}'
    target.write_text(original, encoding="utf-8")

    def partial_then_fail(handle: Any, _text: str) -> None:
        handle.write('{"status":')
        handle.flush()
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(atomic_files, "_write_text_file", partial_then_fail)

    with pytest.raises(OSError, match="interrupted write"):
        atomic_files.atomic_write_json(target, {"status": {"status": "failed"}})

    assert target.read_text(encoding="utf-8") == original
    assert json.loads(target.read_text(encoding="utf-8"))["status"]["status"] == "done"
    assert temporary_files(target) == []


def test_failed_first_write_and_serialisation_leave_no_final_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interrupted = tmp_path / "new-status.json"

    def fail_write(_handle: Any, _text: str) -> None:
        raise OSError("simulated first-write failure")

    monkeypatch.setattr(atomic_files, "_write_text_file", fail_write)

    with pytest.raises(OSError, match="first-write failure"):
        atomic_files.atomic_write_json(interrupted, {"status": "queued"})

    assert not interrupted.exists()
    assert temporary_files(interrupted) == []

    malformed = tmp_path / "malformed.json"
    with pytest.raises(TypeError):
        atomic_files.atomic_write_json(malformed, {"unsupported": Path("value")})

    assert not malformed.exists()
    assert temporary_files(malformed) == []


def test_job_metadata_status_and_state_use_shared_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(job_queue, "jobs_dir", lambda: jobs_root)

    calls: list[Path] = []
    real_write = atomic_files.atomic_write_json

    def record_write(path: Path, value: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        real_write(Path(path), value, **kwargs)

    monkeypatch.setattr(job_queue, "atomic_write_json", record_write)

    _, job_dir = job_queue.create_job(
        title="Atomic fixture",
        markdown="# Atomic fixture\n",
        state="test",
    )
    job_queue.write_status(
        job_dir,
        status="running",
        step="test",
        message="Testing",
    )
    job_queue.set_job_state(job_dir, "archived")

    assert [path.name for path in calls].count("metadata.json") == 1
    assert [path.name for path in calls].count("status.json") == 3
    assert json.loads((job_dir / "metadata.json").read_text(encoding="utf-8"))["job_id"] == job_dir.name
    final_status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert final_status["state"] == "archived"
    assert final_status["status"] == "running"
    assert temporary_files(job_dir / "metadata.json") == []
    assert temporary_files(job_dir / "status.json") == []


def test_cleanup_archiving_uses_shared_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(job_queue, "jobs_dir", lambda: jobs_root)

    _, job_dir = job_queue.create_job(
        title="Old test fixture",
        markdown="# Old fixture\n",
        state="test",
    )
    metadata_path = job_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["created_at"] = "2020-01-01T00:00:00+00:00"
    atomic_files.atomic_write_json(metadata_path, metadata)
    job_queue.write_status(job_dir, status="done", step="complete", message="Done")

    calls: list[Path] = []
    real_write = atomic_files.atomic_write_json

    def record_write(path: Path, value: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        real_write(Path(path), value, **kwargs)

    monkeypatch.setattr(job_queue, "atomic_write_json", record_write)

    result = job_queue.cleanup_old_test_jobs(older_than_days=30, dry_run=False)

    assert result["archived_count"] == 1
    assert calls == [job_dir / "status.json"]
    assert json.loads((job_dir / "status.json").read_text(encoding="utf-8"))["state"] == "archived"


def test_pipeline_manifest_uses_shared_atomic_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_dir = tmp_path / "job"
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True)
    (job_dir / "input" / "book.md").write_text("# Atomic manifest\n", encoding="utf-8")

    outputs = {
        "pdf_standard": "book-standard.pdf",
        "pdf_nd": "book-nd.pdf",
        "epub": "book.epub",
        "docx": "book.docx",
    }

    def export_with_outputs(
        _cleaned: Path,
        output_dir: Path,
        _log_file: Path,
        **_kwargs: object,
    ) -> dict[str, str]:
        for key, filename in outputs.items():
            (output_dir / filename).write_bytes(key.encode("utf-8"))
        return outputs

    monkeypatch.setattr(run_pipeline, "structural_cleanup", lambda raw: raw)
    monkeypatch.setattr(run_pipeline, "pandoc_export", export_with_outputs)

    calls: list[Path] = []
    real_write = atomic_files.atomic_write_json

    def record_write(path: Path, value: Any, **kwargs: Any) -> None:
        calls.append(Path(path))
        real_write(Path(path), value, **kwargs)

    monkeypatch.setattr(run_pipeline, "atomic_write_json", record_write)

    result = run_pipeline.run_pipeline(job_dir)

    assert result == 0
    assert calls == [job_dir / "manifest.json"]
    manifest = json.loads((job_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"]["status"] == "done"
    assert manifest["outputs"] == outputs
    assert temporary_files(job_dir / "manifest.json") == []
