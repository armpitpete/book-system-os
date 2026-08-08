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
from app.utils.paths import filters_dir, templates_dir


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


def _default_resource_dir(markdown_file: Path) -> Path:
    parent = markdown_file.parent.resolve(strict=False)
    if parent.name == "work":
        input_dir = parent.parent / "input"
        if input_dir.is_dir():
            return input_dir.resolve(strict=False)
    return parent


def _resource_path(markdown_file: Path, resource_dir: Path | None) -> str:
    primary = (
        resource_dir.resolve(strict=False)
        if resource_dir is not None
        else _default_resource_dir(markdown_file)
    )
    roots: list[Path] = []
    for candidate in (primary, markdown_file.parent.resolve(strict=False)):
        if candidate not in roots:
            roots.append(candidate)
    return os.pathsep.join(str(path) for path in roots)


def _pandoc_command(
    markdown_file: Path,
    output: PublishOutputSpec,
    *,
    resource_dir: Path | None = None,
) -> list[str]:
    holder_filter = filters_dir() / "image_holder_render.lua"
    if not holder_filter.is_file():
        raise RuntimeError(f"Image-holder rendering filter is unavailable: {holder_filter}")

    cmd = [
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block+link_attributes",
        "--toc",
        f"--lua-filter={holder_filter}",
        f"--resource-path={_resource_path(markdown_file, resource_dir)}",
    ]

    if output.key in {"pdf_standard", "pdf_nd"}:
        cmd.extend(
            [
                "--top-level-division=chapter",
                "--pdf-engine=xelatex",
            ]
        )

        template_name = {
            "pdf_standard": "book-template-standard.tex",
            "pdf_nd": "book-template-nd.tex",
        }[output.key]
        template = templates_dir() / template_name
        if template.exists():
            cmd.append(f"--template={template}")

    cmd.extend(["-o", output.filename])
    return cmd


def pandoc_export(
    markdown_file: Path,
    output_dir: Path,
    log_file: Path,
    *,
    resource_dir: Path | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    job_dir = output_dir.parent

    for output in PUBLISH_OUTPUTS:
        output_path = output_dir / output.filename
        cmd = _pandoc_command(
            markdown_file,
            output,
            resource_dir=resource_dir,
        )
        cmd[-1] = str(output_path)
        _run_export_command(cmd, job_dir=job_dir, log_file=log_file)
        outputs[output.key] = output_path.name

    return outputs
