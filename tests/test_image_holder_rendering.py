from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.exporters import _pandoc_command, pandoc_export
from app.pipeline.input_validation import ManuscriptInputError, validate_local_image_files
from app.services.publish_plan import PUBLISH_OUTPUTS


REPO_ROOT = Path(__file__).resolve().parents[1]
HOLDER_FILTER = REPO_ROOT / "filters" / "image_holder_render.lua"


def require_pandoc() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for image-holder rendering tests")


def require_export_toolchain() -> None:
    if shutil.which("pandoc") is None or shutil.which("xelatex") is None:
        pytest.skip("pandoc and xelatex are required for four-format holder rendering")


def make_image(path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="PNG")


def make_valid_holder_images(input_dir: Path) -> None:
    assets = input_dir / "assets"
    make_image(assets / "inline.png", (1400, 900))
    make_image(assets / "feature.png", (2400, 1600))
    make_image(assets / "portrait.png", (1400, 2000))
    make_image(assets / "full-page.png", (2100, 2800))
    make_image(assets / "ornament.png", (1200, 1200))


def holder_manuscript() -> str:
    return (
        "---\n"
        "title: Holder rendering proof\n"
        "lang: en-GB\n"
        "---\n\n"
        "# Holder rendering proof\n\n"
        "Inline text ![Inline accessibility text](assets/inline.png)"
        '{holder=inline width="1in" height="2in" style="position: fixed; width: 1px" latex-placement="t"} '
        "continues after the image.\n\n"
        "![Feature accessibility text](assets/feature.png)"
        '{holder=feature caption="Feature visible caption."}\n\n'
        "![Portrait accessibility text](assets/portrait.png){holder=portrait}\n\n"
        "![Full-page accessibility text](assets/full-page.png)"
        '{holder=full-page caption="Full-page visible caption."}\n\n'
        "![](assets/ornament.png){holder=ornament decorative=true}\n"
    )


def _run_latex_render(markdown: str, template: Path, resource_dir: Path) -> str:
    completed = subprocess.run(
        [
            "pandoc",
            "--from=markdown+yaml_metadata_block+link_attributes",
            "--to=latex",
            f"--template={template}",
            f"--lua-filter={HOLDER_FILTER}",
            f"--resource-path={resource_dir}",
        ],
        input=markdown,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout


def _epub_xhtml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html"))
        )


def _docx_document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8", errors="replace")


def test_all_publish_commands_use_holder_filter_and_infer_manuscript_resource_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(REPO_ROOT))
    input_dir = tmp_path / "input"
    work_dir = tmp_path / "work"
    input_dir.mkdir()
    work_dir.mkdir()
    markdown = work_dir / "book-clean.md"
    markdown.write_text("# Book\n", encoding="utf-8")

    for output in PUBLISH_OUTPUTS:
        command = _pandoc_command(markdown, output)
        assert "--from=markdown+yaml_metadata_block+link_attributes" in command
        assert f"--lua-filter={HOLDER_FILTER}" in command
        resource_argument = next(
            value for value in command if value.startswith("--resource-path=")
        )
        roots = resource_argument.removeprefix("--resource-path=").split(os.pathsep)
        assert str(input_dir.resolve()) in roots
        assert str(work_dir.resolve()) in roots


def test_caption_required_holder_must_be_standalone_figure(tmp_path: Path) -> None:
    require_pandoc()
    make_image(tmp_path / "feature.png", (2400, 1600))

    with pytest.raises(ManuscriptInputError) as exc:
        validate_local_image_files(
            'Before ![Feature accessibility text](feature.png){holder=feature caption="Visible caption."} after.\n',
            source_dir=tmp_path,
        )

    assert exc.value.code == "image-holder-requires-figure-context"


def test_caption_required_standalone_holder_remains_valid(tmp_path: Path) -> None:
    require_pandoc()
    make_image(tmp_path / "feature.png", (2400, 1600))

    validate_local_image_files(
        '![Feature accessibility text](feature.png){holder=feature caption="Visible caption."}\n',
        source_dir=tmp_path,
    )


@pytest.mark.parametrize(
    ("template_name", "label"),
    [
        ("book-template-standard.tex", "pdf_standard"),
        ("book-template-nd.tex", "pdf_nd"),
    ],
)
def test_pdf_holder_mapping_is_deterministic_latex(
    tmp_path: Path,
    template_name: str,
    label: str,
) -> None:
    require_pandoc()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_valid_holder_images(input_dir)
    markdown = holder_manuscript()

    validate_local_image_files(markdown, source_dir=input_dir)
    latex = _run_latex_render(markdown, REPO_ROOT / "templates" / template_name, input_dir)

    assert "width=5.5in" in latex, label
    assert "width=6.25in" in latex, label
    assert "width=3.5in" in latex, label
    assert "width=1in" in latex, label
    assert "Feature visible caption." in latex, label
    assert "Full-page visible caption." in latex, label
    assert "Portrait accessibility text" not in latex, label
    assert latex.count("\\clearpage") >= 2, label
    assert "position: fixed" not in latex, label


@pytest.mark.integration
def test_validated_relative_holders_render_in_all_four_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_export_toolchain()
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(REPO_ROOT))

    input_dir = tmp_path / "input"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "output"
    log_file = tmp_path / "logs" / "build.log"
    input_dir.mkdir()
    work_dir.mkdir()
    make_valid_holder_images(input_dir)

    markdown = holder_manuscript()
    validate_local_image_files(markdown, source_dir=input_dir)
    cleaned = work_dir / "book-clean.md"
    cleaned.write_text(markdown, encoding="utf-8")

    outputs = pandoc_export(cleaned, output_dir, log_file)

    assert set(outputs) == {"pdf_standard", "pdf_nd", "epub", "docx"}
    for key in ("pdf_standard", "pdf_nd"):
        pdf = output_dir / outputs[key]
        data = pdf.read_bytes()
        assert data.startswith(b"%PDF-")
        assert b"%%EOF" in data[-4096:]

    epub = output_dir / outputs["epub"]
    assert zipfile.is_zipfile(epub)
    xhtml = _epub_xhtml(epub)
    for holder, width in (
        ("inline", "5.5in"),
        ("feature", "6.25in"),
        ("portrait", "3.5in"),
        ("full-page", "6.25in"),
        ("ornament", "1in"),
    ):
        assert f"book-system-holder-{holder}" in xhtml
        assert f"width:{width}" in xhtml.replace(" ", "")
    assert "Feature visible caption." in xhtml
    assert "Full-page visible caption." in xhtml
    assert xhtml.count("book-system-page-break") >= 2
    assert 'role="presentation"' in xhtml
    assert 'aria-hidden="true"' in xhtml
    assert "position: fixed" not in xhtml

    docx = output_dir / outputs["docx"]
    assert zipfile.is_zipfile(docx)
    document = _docx_document_xml(docx)
    assert "Feature visible caption." in document
    assert "Full-page visible caption." in document
    assert document.count('w:type="page"') >= 2
    assert 'cx="5029200"' in document  # 5.5 in inline holder
    assert 'cx="3200400"' in document  # 3.5 in portrait holder
    assert 'cx="914400"' in document  # 1 in ornament holder

    build_log = log_file.read_text(encoding="utf-8", errors="replace")
    assert build_log.count("--lua-filter=") == 4
    assert build_log.count("--resource-path=") == 4
    assert "book-standard.pdf" in build_log
    assert "book-nd.pdf" in build_log
