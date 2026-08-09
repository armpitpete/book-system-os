from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AcceptanceError(message)


def git_value(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"git verification failed: {type(exc).__name__}")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"absent\0")
        return digest.hexdigest()
    if root.is_symlink() or not root.is_dir():
        fail(f"persistent root is not a safe directory: {root.name}")
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode(
            "utf-8", errors="surrogateescape"
        )
        metadata = path.lstat()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(stat.S_IMODE(metadata.st_mode)).encode("ascii"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_dir():
            digest.update(b"directory\0")
        elif path.is_file():
            digest.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            digest.update(b"other\0")
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_image(Image: Any, path: Path, size: tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path, format="PNG")


def _holder_manuscript() -> str:
    return (
        "---\n"
        "title: Production holder rendering proof\n"
        "lang: en-GB\n"
        "---\n\n"
        "# Production holder rendering proof\n\n"
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


def _epub_xhtml(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
                if name.lower().endswith((".xhtml", ".html"))
            )
    except (OSError, zipfile.BadZipFile) as exc:
        fail(f"EPUB inspection failed: {type(exc).__name__}")


def _docx_document_xml(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode(
                "utf-8", errors="replace"
            )
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        fail(f"DOCX inspection failed: {type(exc).__name__}")


def _rendering_checks(
    repo_root: Path,
    Image: Any,
    validate_local_image_files: Any,
    pandoc_export: Any,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="book-system-image-holder-v02-") as raw:
        root = Path(raw)
        input_dir = root / "input"
        work_dir = root / "work"
        output_dir = root / "output"
        log_file = root / "logs" / "build.log"
        input_dir.mkdir()
        work_dir.mkdir()

        assets = input_dir / "assets"
        _make_image(Image, assets / "inline.png", (1400, 900))
        _make_image(Image, assets / "feature.png", (2400, 1600))
        _make_image(Image, assets / "portrait.png", (1400, 2000))
        _make_image(Image, assets / "full-page.png", (2100, 2800))
        _make_image(Image, assets / "ornament.png", (1200, 1200))

        markdown = _holder_manuscript()
        validate_local_image_files(markdown, source_dir=input_dir)
        cleaned = work_dir / "book-clean.md"
        cleaned.write_text(markdown, encoding="utf-8")

        try:
            outputs = pandoc_export(cleaned, output_dir, log_file)
        except Exception as exc:
            fail(f"four-format holder rendering failed: {type(exc).__name__}: {exc}")

        expected_outputs = {"pdf_standard", "pdf_nd", "epub", "docx"}
        if set(outputs) != expected_outputs:
            fail("four-format holder rendering returned an unexpected output set")

        output_records: dict[str, dict[str, Any]] = {}
        for key, filename in outputs.items():
            path = output_dir / filename
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                fail(f"rendered output is missing or invalid: {key}")
            output_records[key] = {
                "filename": filename,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }

        for key in ("pdf_standard", "pdf_nd"):
            data = (output_dir / outputs[key]).read_bytes()
            if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
                fail(f"rendered PDF failed structural signature check: {key}")

        epub = output_dir / outputs["epub"]
        if not zipfile.is_zipfile(epub):
            fail("rendered EPUB is not a valid ZIP container")
        xhtml = _epub_xhtml(epub)
        compact_xhtml = xhtml.replace(" ", "")
        for holder, width in (
            ("inline", "5.5in"),
            ("feature", "6.25in"),
            ("portrait", "3.5in"),
            ("full-page", "6.25in"),
            ("ornament", "1in"),
        ):
            if f"book-system-holder-{holder}" not in xhtml:
                fail(f"EPUB is missing holder class: {holder}")
            if f"width:{width}" not in compact_xhtml:
                fail(f"EPUB is missing controlled holder width: {holder}")
        if "Feature visible caption." not in xhtml:
            fail("EPUB is missing feature caption")
        if "Full-page visible caption." not in xhtml:
            fail("EPUB is missing full-page caption")
        if xhtml.count("book-system-page-break") < 2:
            fail("EPUB is missing deterministic full-page page breaks")
        if 'role="presentation"' not in xhtml or 'aria-hidden="true"' not in xhtml:
            fail("EPUB ornament decorative semantics are missing")
        if "position: fixed" in xhtml:
            fail("EPUB retained forbidden author positioning metadata")

        docx = output_dir / outputs["docx"]
        if not zipfile.is_zipfile(docx):
            fail("rendered DOCX is not a valid ZIP container")
        document = _docx_document_xml(docx)
        if "Feature visible caption." not in document:
            fail("DOCX is missing feature caption")
        if "Full-page visible caption." not in document:
            fail("DOCX is missing full-page caption")
        if document.count('w:type="page"') < 2:
            fail("DOCX is missing deterministic full-page page breaks")
        for width in ('cx="5029200"', 'cx="3200400"', 'cx="914400"'):
            if width not in document:
                fail(f"DOCX is missing controlled holder width: {width}")
        if "position: fixed" in document:
            fail("DOCX retained forbidden author positioning metadata")

        holder_filter = repo_root / "filters" / "image_holder_render.lua"
        if not holder_filter.is_file():
            fail("image-holder v0.2 rendering filter is unavailable")
        renderer_sha256 = _sha256_file(holder_filter)
        build_log = log_file.read_text(encoding="utf-8", errors="replace")
        if build_log.count("--lua-filter=filters/image_holder_render.lua") != 4:
            fail("production export path did not invoke the holder filter four times")
        if build_log.count("--resource-path=") != 4:
            fail("production export path did not bind resource roots four times")
        renderer_binding = (
            "--variable=book-system-holder-renderer-sha256=" + renderer_sha256
        )
        if build_log.count(renderer_binding) != 4:
            fail("production export path did not bind the exact renderer digest")

        return {
            "four_format_rendering": "pass",
            "pdf_standard": "pass",
            "pdf_nd": "pass",
            "docx_structure": "pass",
            "epub_structure": "pass",
            "relative_input_resource_resolution": "pass",
            "author_positioning_sanitised": "pass",
            "renderer_sha256": renderer_sha256,
            "build_log_sha256": _sha256_file(log_file),
            "outputs": output_records,
        }


def check_image_holder_runtime(repo_root: Path) -> dict[str, Any]:
    os.environ["BOOK_SYSTEM_ROOT"] = str(repo_root)
    sys.path.insert(0, str(repo_root))
    try:
        import PIL
        from PIL import Image
        from app.pipeline.exporters import pandoc_export
        from app.pipeline.input_validation import (
            ManuscriptInputError,
            validate_local_image_files,
        )
    except Exception as exc:
        fail(f"image-holder runtime import failed: {type(exc).__name__}")

    if PIL.__version__ != "12.3.0":
        fail(f"unexpected Pillow runtime version: {PIL.__version__}")

    with tempfile.TemporaryDirectory(prefix="book-system-image-holder-validation-") as raw:
        root = Path(raw)
        safe = root / "safe.png"
        low = root / "low.png"
        Image.new("RGB", (2400, 1600), "white").save(safe, format="PNG")
        Image.new("RGB", (600, 400), "white").save(low, format="PNG")

        validate_local_image_files(
            '![Representative image](safe.png){holder=feature caption="Representative image."}\n',
            source_dir=root,
        )

        try:
            validate_local_image_files(
                "![Low resolution](low.png){holder=inline}\n",
                source_dir=root,
            )
        except ManuscriptInputError as exc:
            if exc.code != "image-resolution-too-low":
                fail(f"low-resolution holder failed with unexpected code: {exc.code}")
        else:
            fail("low-resolution holder input did not fail closed")

        try:
            validate_local_image_files(
                "![Remote](https://example.invalid/image.png){holder=inline}\n",
                source_dir=root,
            )
        except ManuscriptInputError as exc:
            if exc.code != "image-holder-requires-local-file":
                fail(f"remote holder failed with unexpected code: {exc.code}")
        else:
            fail("remote holder input did not fail closed")

    checks: dict[str, Any] = {
        "pillow_version": PIL.__version__,
        "representative_holder": "pass",
        "low_resolution_fail_closed": "pass",
        "remote_holder_fail_closed": "pass",
    }
    checks.update(
        _rendering_checks(
            repo_root,
            Image,
            validate_local_image_files,
            pandoc_export,
        )
    )
    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run non-mutating production smoke checks for image-holder rendering v0.2."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    expected = args.expected_commit.strip()
    evidence_dir = args.evidence_dir.resolve()

    if len(expected) != 40 or any(c not in "0123456789abcdef" for c in expected):
        fail("expected commit must be a full lowercase SHA-1")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production repository is not at the exact expected commit")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("production repository is not clean before image-holder acceptance")

    jobs_root = repo_root / "books" / "jobs"
    revisions_root = repo_root / "books" / "revisions"
    jobs_before = _tree_digest(jobs_root)
    revisions_before = _tree_digest(revisions_root)

    checks = check_image_holder_runtime(repo_root)

    if _tree_digest(jobs_root) != jobs_before:
        fail("image-holder acceptance changed retained job state")
    if _tree_digest(revisions_root) != revisions_before:
        fail("image-holder acceptance changed Revision Studio state")
    if git_value(repo_root, "rev-parse", "HEAD") != expected:
        fail("production commit changed during image-holder acceptance")
    if git_value(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        fail("image-holder acceptance left repository changes")

    report = {
        "expected_commit": expected,
        "contract": "image-holder-rendering-v0.2-live-acceptance",
        "checks": checks,
        "retained_jobs_unchanged": True,
        "revision_state_unchanged": True,
    }
    evidence_dir.mkdir(parents=True, exist_ok=False)
    evidence_path = evidence_dir / "image-holder-live-acceptance.json"
    evidence_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(evidence_path, 0o600)
    os.chmod(evidence_dir, 0o700)

    print("image-holder-live-acceptance=pass")
    print("image-holder-rendering-v0.2-live-acceptance=pass")
    print(f"expected-commit={expected}")
    print("pillow-version=12.3.0")
    print("representative-holder=pass")
    print("low-resolution-fail-closed=pass")
    print("remote-holder-fail-closed=pass")
    print("four-format-rendering=pass")
    print("pdf-standard=pass")
    print("pdf-nd=pass")
    print("docx-structure=pass")
    print("epub-structure=pass")
    print("relative-input-resource-resolution=pass")
    print("author-positioning-sanitised=pass")
    print("retained-job-state-unchanged=true")
    print("revision-state-unchanged=true")
    print(f"renderer-sha256={checks['renderer_sha256']}")
    print(f"evidence={evidence_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(f"image-holder-live-acceptance=fail: {exc}", file=sys.stderr)
        raise SystemExit(1)
