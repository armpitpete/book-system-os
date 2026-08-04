from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import app.pipeline.run_pipeline as pipeline_module
from app.pipeline.input_validation import validate_local_image_files
from app.services.publish_plan import PUBLISH_OUTPUTS


def require_pandoc() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for image-reference input validation")


def prepare_job(tmp_path: Path, manuscript: str, name: str) -> Path:
    job_dir = tmp_path / name
    for directory in ("input", "work", "output", "logs"):
        (job_dir / directory).mkdir(parents=True, exist_ok=True)
    (job_dir / "input" / "book.md").write_text(manuscript, encoding="utf-8")
    return job_dir


def fake_outputs(job_dir: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for output in PUBLISH_OUTPUTS:
        (job_dir / "output" / output.filename).write_bytes(
            b"deterministic non-empty test output"
        )
        outputs[output.key] = output.filename
    return outputs


@pytest.mark.parametrize(
    "target",
    [
        "/definitely-not-present/book-system-os/missing-image.png",
        "assets/missing-image.png",
    ],
)
def test_missing_local_image_fails_before_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    require_pandoc()
    manuscript = f"# Missing image\n\n![Absent image](<{target}>)\n"
    job_dir = prepare_job(tmp_path, manuscript, "missing-local-image")
    export_called = False

    def unexpected_export(*_args, **_kwargs):
        nonlocal export_called
        export_called = True
        raise AssertionError("export must not start for a missing local image")

    monkeypatch.setattr(pipeline_module, "pandoc_export", unexpected_export)

    result = pipeline_module.run_pipeline(job_dir)

    assert result == 1
    assert export_called is False
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["step"] == "input-validation"
    assert status["failure_code"] == "missing-image-file"
    assert target in status["message"]
    assert not any((job_dir / "output").iterdir())
    assert not (job_dir / "manifest.json").exists()
    assert not (job_dir / "logs" / "build.log").exists()

    error_log = (job_dir / "logs" / "error.log").read_text(encoding="utf-8")
    assert "ManuscriptInputError" in error_log
    assert "pandoc_export" not in error_log
    assert "xelatex" not in error_log.lower()


def test_existing_absolute_image_reaches_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_pandoc()
    image = tmp_path / "existing image.png"
    image.write_bytes(b"not decoded because the exporter is replaced")
    manuscript = f"# Existing image\n\n![Present image](<{image}>)\n"
    job_dir = prepare_job(tmp_path, manuscript, "existing-local-image")
    export_called = False

    def successful_export(_markdown: Path, output_dir: Path, _log: Path):
        nonlocal export_called
        export_called = True
        assert output_dir == job_dir / "output"
        return fake_outputs(job_dir)

    monkeypatch.setattr(pipeline_module, "pandoc_export", successful_export)

    result = pipeline_module.run_pipeline(job_dir)

    assert result == 0
    assert export_called is True
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "done"
    assert (job_dir / "manifest.json").is_file()


def test_non_local_image_targets_are_not_fetched_or_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_pandoc()
    calls: list[tuple[tuple, dict]] = []

    def forbidden_path_check(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("non-local image target must not be checked as a path")

    monkeypatch.setattr(Path, "is_file", forbidden_path_check)
    validate_local_image_files(
        "# Images\n\n![Data](data:image/png;base64,AA==)\n\n"
        "![Remote](https://example.invalid/image.png)\n",
        source_dir=tmp_path,
    )
    assert calls == []
