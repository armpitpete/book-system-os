from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.pipeline.exporters import _pandoc_command
from app.services.publish_plan import PUBLISH_OUTPUTS

REPO_ROOT = Path(__file__).resolve().parents[1]


def require_pandoc() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for TOC regression tests")


def test_all_publish_commands_limit_toc_to_top_level_units() -> None:
    for output in PUBLISH_OUTPUTS:
        command = _pandoc_command(Path("book.md"), output)
        assert "--toc" in command
        assert "--toc-depth=1" in command


def test_epub_and_docx_toc_exclude_internal_headings(tmp_path: Path) -> None:
    require_pandoc()
    markdown = tmp_path / "book.md"
    markdown.write_text(
        "# Unit One\n\n## Internal section\n\n### Fine detail\n\n"
        "# Unit Two\n\n## Another internal section\n",
        encoding="utf-8",
    )

    for key in ("epub", "docx"):
        spec = next(output for output in PUBLISH_OUTPUTS if output.key == key)
        command = _pandoc_command(markdown, spec)
        command[command.index("-o") + 1] = str(tmp_path / spec.filename)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    with zipfile.ZipFile(tmp_path / "book.epub") as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8", errors="replace")
    toc_nav = nav.split('<nav epub:type="toc"', 1)[1].split("</nav>", 1)[0]
    assert "Unit One" in toc_nav
    assert "Unit Two" in toc_nav
    assert "Internal section" not in toc_nav
    assert "Fine detail" not in toc_nav
    assert "Another internal section" not in toc_nav

    with zipfile.ZipFile(tmp_path / "book.docx") as archive:
        document = archive.read("word/document.xml").decode("utf-8", errors="replace")
    assert 'TOC \\o &quot;1-1&quot; \\h \\z \\u' in document


def test_pdf_templates_honour_top_level_toc_depth(tmp_path: Path) -> None:
    require_pandoc()
    markdown = tmp_path / "book.md"
    markdown.write_text(
        "# Unit One\n\n## Internal section\n\n### Fine detail\n\n# Unit Two\n",
        encoding="utf-8",
    )

    for template_name in ("book-template-standard.tex", "book-template-nd.tex"):
        completed = subprocess.run(
            [
                "pandoc",
                str(markdown),
                "--from=markdown+yaml_metadata_block+link_attributes",
                "--to=latex",
                "--standalone",
                "--toc",
                "--toc-depth=1",
                "--top-level-division=chapter",
                f"--template={REPO_ROOT / 'templates' / template_name}",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert r"\setcounter{tocdepth}{0}" in completed.stdout
