from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services import readiness_guard
from app.services.pandoc_capability import PandocSandboxCapability
from scripts import reconcile_runtime_requirements


_READINESS_BEHAVIOUR_TESTS = {
    "test_readiness.py",
    "test_readiness_crash_loop_regression.py",
}

_RUNTIME_REQUIREMENT_SEQUENCE_TEST = (
    "test_reconciliation_downloads_all_wheels_before_local_install_then_pip_check"
)


def _compatible_pandoc() -> PandocSandboxCapability:
    return PandocSandboxCapability(
        compatible=True,
        code="pandoc-sandbox-compatible",
        message="Pandoc sandbox capability is available",
        return_code=0,
    )


@pytest.fixture(autouse=True)
def isolate_readiness_behaviour_from_external_pandoc(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep worker/readiness tests focused on their named behaviour.

    Those tests replace ``shutil.which`` in the base readiness module. Python
    modules share the same imported ``shutil`` object, so that replacement can
    otherwise redirect the separate functional Pandoc probe to a fake
    ``/usr/bin/pandoc``. Real and failure-path Pandoc capability remains covered
    by ``test_toolchain_compatibility.py``.

    The runtime-requirement sequencing unit test likewise fakes successful pip
    installs without creating distribution metadata on disk. Keep that test
    focused on download/install/check ordering; real restrictive-umask and
    installed-file permission behaviour is exercised by the dedicated runtime
    install-permissions integration test.
    """

    readiness_guard._reset_pandoc_readiness_cache()
    if request.path.name in _READINESS_BEHAVIOUR_TESTS:
        monkeypatch.setattr(
            readiness_guard,
            "probe_pandoc_sandbox",
            _compatible_pandoc,
        )
    if (
        request.path.name == "test_runtime_requirement_deployment.py"
        and request.node.name == _RUNTIME_REQUIREMENT_SEQUENCE_TEST
    ):
        monkeypatch.setattr(
            reconcile_runtime_requirements,
            "_verify_service_readable_additions",
            lambda requirements: None,
        )
    yield
    readiness_guard._reset_pandoc_readiness_cache()
