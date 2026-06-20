from __future__ import annotations

import subprocess
from pathlib import Path

from app.utils.paths import templates_dir


def run_command(cmd: list[str], log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(cmd) + "\n")
        result = subprocess.run(cmd, stdout=log, stderr=log, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")


def pandoc_export(markdown_file: Path, output_dir: Path, log_file: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}

    standard_template = templates_dir() / "book-template-standard.tex"
    nd_template = templates_dir() / "book-template-nd.tex"

    pdf_standard = output_dir / "book-standard.pdf"
    cmd = [
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block",
        "--pdf-engine=xelatex",
        "--toc",
        "-o",
        str(pdf_standard),
    ]
    if standard_template.exists():
        cmd.insert(2, f"--template={standard_template}")
    run_command(cmd, log_file)
    outputs["pdf_standard"] = pdf_standard.name

    pdf_nd = output_dir / "book-nd.pdf"
    cmd = [
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block",
        "--pdf-engine=xelatex",
        "--toc",
        "-o",
        str(pdf_nd),
    ]
    if nd_template.exists():
        cmd.insert(2, f"--template={nd_template}")
    run_command(cmd, log_file)
    outputs["pdf_nd"] = pdf_nd.name

    epub = output_dir / "book.epub"
    run_command([
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block",
        "--toc",
        "-o",
        str(epub),
    ], log_file)
    outputs["epub"] = epub.name

    docx = output_dir / "book.docx"
    run_command([
        "pandoc",
        str(markdown_file),
        "--from=markdown+yaml_metadata_block",
        "--toc",
        "-o",
        str(docx),
    ], log_file)
    outputs["docx"] = docx.name

    return outputs
