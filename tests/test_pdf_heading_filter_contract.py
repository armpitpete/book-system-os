from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pdf_heading_filter_preserves_source_labels() -> None:
    renderer = (REPO_ROOT / "filters" / "image_holder_render.lua").read_text(encoding="utf-8")
    assert 'FORMAT:match("latex") and header.level == 1' in renderer
    assert 'add_class(header.classes, "unnumbered")' in renderer
