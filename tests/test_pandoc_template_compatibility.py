from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "template_name",
    ["book-template-standard.tex", "book-template-nd.tex"],
)
def test_custom_latex_templates_define_official_pandocbounded_contract(
    template_name: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / template_name).read_text(encoding="utf-8")

    required_fragments = [
        r"\newsavebox\pandoc@box",
        r"\newcommand*\pandocbounded[1]",
        r"\Gscale@div\@tempa{\textheight}",
        r"\Gscale@div\@tempb{\linewidth}",
        r"\scalebox{\@tempa}{\usebox\pandoc@box}",
    ]
    for fragment in required_fragments:
        assert fragment in template


@pytest.mark.parametrize(
    "template_name",
    ["book-template-standard.tex", "book-template-nd.tex"],
)
def test_custom_latex_templates_include_pandoc_highlighting_macros(
    template_name: str,
) -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / template_name).read_text(encoding="utf-8")

    assert "$if(highlighting-macros)$" in template
    assert "$highlighting-macros$" in template
    assert "$endif$" in template
