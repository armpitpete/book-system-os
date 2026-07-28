from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Sequence

PANDOC_DOCUMENTED_MINIMUM_VERSION = "2.15"
PANDOC_SANDBOX_PROBE_TIMEOUT_SECONDS = 5.0
_PANDOC_SANDBOX_PROBE_INPUT = b"# Book System OS sandbox capability probe\n"


@dataclass(frozen=True)
class PandocSandboxCapability:
    compatible: bool
    code: str
    message: str
    return_code: int | None = None


def _command(executable: str) -> list[str]:
    return [
        executable,
        "--sandbox",
        "--from=markdown+yaml_metadata_block",
        "--to=json",
    ]


def probe_pandoc_sandbox(
    *,
    executable: str | None = None,
    timeout_seconds: float = PANDOC_SANDBOX_PROBE_TIMEOUT_SECONDS,
) -> PandocSandboxCapability:
    """Prove the required Pandoc sandbox capability with fixed bounded input.

    Version text is deliberately not authority. A compatible executable must
    successfully parse a fixed Markdown document through the same sandboxed
    JSON path used by manuscript validation.
    """

    resolved = executable or shutil.which("pandoc")
    if not resolved:
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-unavailable",
            message="Pandoc is unavailable",
        )

    try:
        completed = subprocess.run(
            _command(resolved),
            input=_PANDOC_SANDBOX_PROBE_INPUT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(0.1, min(float(timeout_seconds), 10.0)),
        )
    except FileNotFoundError:
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-unavailable",
            message="Pandoc is unavailable",
        )
    except subprocess.TimeoutExpired:
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-sandbox-probe-timeout",
            message="Pandoc sandbox capability probe timed out",
        )
    except OSError:
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-sandbox-probe-failed",
            message="Pandoc sandbox capability probe could not run",
        )

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").lower()
        unsupported = "unknown option" in stderr and "sandbox" in stderr
        return PandocSandboxCapability(
            compatible=False,
            code=(
                "pandoc-sandbox-unsupported"
                if unsupported
                else "pandoc-sandbox-probe-failed"
            ),
            message=(
                "Pandoc does not support the required sandbox capability"
                if unsupported
                else "Pandoc sandbox capability probe failed"
            ),
            return_code=completed.returncode,
        )

    try:
        payload = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-sandbox-invalid-response",
            message="Pandoc sandbox capability probe returned invalid JSON",
            return_code=completed.returncode,
        )

    if not isinstance(payload, dict) or not isinstance(payload.get("blocks"), list):
        return PandocSandboxCapability(
            compatible=False,
            code="pandoc-sandbox-invalid-response",
            message="Pandoc sandbox capability probe returned an invalid document",
            return_code=completed.returncode,
        )

    return PandocSandboxCapability(
        compatible=True,
        code="pandoc-sandbox-compatible",
        message="Pandoc sandbox capability is available",
        return_code=completed.returncode,
    )


def pandoc_sandbox_command(executable: str) -> Sequence[str]:
    """Expose the authoritative command shape for focused contract tests."""

    return tuple(_command(executable))
