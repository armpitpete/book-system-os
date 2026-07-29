from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.services import readiness_guard
from app.services.pandoc_capability import PandocSandboxCapability


_READINESS_BEHAVIOUR_TESTS = {
    "test_readiness.py",
    "test_readiness_crash_loop_regression.py",
}


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
    """

    readiness_guard._reset_pandoc_readiness_cache()
    if request.path.name in _READINESS_BEHAVIOUR_TESTS:
        monkeypatch.setattr(
            readiness_guard,
            "probe_pandoc_sandbox",
            _compatible_pandoc,
        )
    yield
    readiness_guard._reset_pandoc_readiness_cache()
