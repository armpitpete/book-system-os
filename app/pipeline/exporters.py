from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from app.services.publish_plan import PUBLISH_OUTPUTS, PublishOutputSpec
from app.services.resource_limits import (
    enforce_job_storage_limits,
    export_command_timeout_seconds,
)
from app.utils.paths import templates_dir


class ExportTimeoutError(RuntimeError):
    """Raised when an export command exceeds the configured runtime limit."""


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()

    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def run_command(
    cmd: list[str],
    log_file: Path,
    *,
    timeout_seconds: float | None = None,
) -> None:
    timeout = (
        export_command_timeout_seconds()
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if timeout <= 0:
        raise ValueError("timeout_seconds must be greater than zero")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(cmd) + "\n")
        log.flush()

        popen_kwargs: dict[str, object] = {
            "stdout": log,
            "stderr": log,
            "text": True,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(cmd, **popen_kwargs)
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process)
            message = (
                f"Command timed out after {timeout:g} seconds: "
                + " ".join(cmd)
            )
            log.write("\nERROR: " + message + "\n")
            log.flush()
            raise ExportTimeoutError(message) from exc

    if return_code != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def _run_export_command(
    cmd: list[str],
    *,
    job_dir: Path,
    log_file: Path,
) -> None:
    run_command(cmd, log_file)
    enforce_job_storage_limits(job_dir)


def _pandoc_command(
    markdown_file: Path,
    output: PublishOutputSpec,
) -> list[str]:
    cmd = [
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block",
        "--toc",
        "-o",
        output.filename,
    ]
    if output.key in {"pdf_standard", "pdf_nd"}:
        cmd.insert(3, "--top-level-division=chapter")
        cmd.insert(4, "--pdf-engine=xelatex")

        template_name = {
            "pdf_standard": "book-template-standard.tex",
            "pdf_nd": "book-template-nd.tex",
        }[output.key]
        template = templates_dir() / template_name
        if template.exists():
            cmd.insert(2, f"--template={template}")
    return cmd


def pandoc_export(markdown_file: Path, output_dir: Path, log_file: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    job_dir = output_dir.parent

    for output in PUBLISH_OUTPUTS:
        output_path = output_dir / output.filename
        cmd = _pandoc_command(markdown_file, output)
        cmd[-1] = str(output_path)
        _run_export_command(cmd, job_dir=job_dir, log_file=log_file)
        outputs[output.key] = output_path.name

    return outputs
