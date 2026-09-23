from __future__ import annotations

import re
from dataclasses import dataclass

_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^\s)]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^\s)]+)(?:\s+[\"'][^\"']*[\"'])?\)")
_FOOTNOTE_REF_RE = re.compile(r"\[\^([A-Za-z0-9._-]+)\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([A-Za-z0-9._-]+)\]:[ \t]+", re.MULTILINE)
_LIST_RE = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+", re.MULTILINE)
_RAW_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
_TABLE_SEPARATOR_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$",
    re.MULTILINE,
)
_SETEXT_RE = re.compile(r"^.+\n(?:=+|-+)[ \t]*$", re.MULTILINE)
_WORD_RE = re.compile(r"\b[\w’'-]+\b", re.UNICODE)
_PAGE_BREAK = "<!-- bos:page-break -->"
_SCENE_BREAKS = {"***", "---", "___"}


@dataclass(frozen=True)
class MarkdownFinding:
    code: str
    severity: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class MarkdownInspection:
    word_count: int
    heading_count: int
    maximum_heading_level: int
    image_count: int
    link_count: int
    footnote_count: int
    list_count: int
    scene_break_count: int
    page_break_count: int
    asset_ids: tuple[str, ...]


@dataclass(frozen=True)
class MarkdownResult:
    canonical_markdown: str
    findings: tuple[MarkdownFinding, ...]
    inspection: MarkdownInspection

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)


def canonicalize_markdown(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _line_of(markdown: str, offset: int) -> int:
    return markdown.count("\n", 0, offset) + 1


def inspect_markdown(markdown: str) -> MarkdownResult:
    canonical = canonicalize_markdown(markdown)
    findings: list[MarkdownFinding] = []

    for index, character in enumerate(canonical):
        if ord(character) < 32 and character not in {"\n", "\t"}:
            findings.append(
                MarkdownFinding(
                    "markdown-control-character",
                    "error",
                    "Markdown contains an unsupported control character.",
                    _line_of(canonical, index),
                )
            )
            break

    if canonical.startswith("---\n"):
        closing = canonical.find("\n---\n", 4)
        if closing != -1:
            findings.append(
                MarkdownFinding(
                    "markdown-embedded-metadata",
                    "error",
                    "Publication metadata is separate from content-unit Markdown.",
                    1,
                )
            )

    if "```" in canonical or "~~~" in canonical:
        findings.append(
            MarkdownFinding(
                "markdown-fenced-code-unsupported",
                "error",
                "Fenced code blocks are outside Book System Markdown v0.1.",
            )
        )

    table_match = _TABLE_SEPARATOR_RE.search(canonical)
    if table_match is not None:
        findings.append(
            MarkdownFinding(
                "markdown-table-unsupported",
                "error",
                "Markdown tables are outside Book System Markdown v0.1.",
                _line_of(canonical, table_match.start()),
            )
        )

    setext_match = _SETEXT_RE.search(canonical)
    if setext_match is not None:
        findings.append(
            MarkdownFinding(
                "markdown-setext-heading-unsupported",
                "error",
                "Use ATX headings (# through ######) rather than Setext headings.",
                _line_of(canonical, setext_match.start()),
            )
        )

    html_match = _RAW_HTML_RE.search(canonical.replace(_PAGE_BREAK, ""))
    if html_match is not None:
        findings.append(
            MarkdownFinding(
                "markdown-raw-html-unsupported",
                "error",
                "Raw HTML is outside Book System Markdown v0.1.",
                _line_of(canonical, html_match.start()),
            )
        )

    heading_levels: list[int] = []
    scene_break_count = 0
    page_break_count = 0
    for line_number, line in enumerate(canonical.splitlines(), start=1):
        stripped = line.strip()
        heading = _ATX_HEADING_RE.match(line)
        if heading:
            heading_levels.append(len(heading.group(1)))
        elif stripped.startswith("#") and len(stripped) > 6 and stripped.startswith("#######"):
            findings.append(
                MarkdownFinding(
                    "markdown-heading-invalid",
                    "error",
                    "Headings must use one to six # characters followed by a space.",
                    line_number,
                )
            )
        if stripped in _SCENE_BREAKS:
            scene_break_count += 1
        if stripped == _PAGE_BREAK:
            page_break_count += 1

    image_matches = list(_IMAGE_RE.finditer(canonical))
    image_targets = [match.group(1) for match in image_matches]
    asset_ids: list[str] = []
    for match, target in zip(image_matches, image_targets):
        if not target.startswith("asset:"):
            findings.append(
                MarkdownFinding(
                    "markdown-image-reference-not-asset",
                    "error",
                    "Images must reference a declared asset using asset:<id>.",
                    _line_of(canonical, match.start()),
                )
            )
            continue
        asset_id = target[6:]
        if _ASSET_ID_RE.fullmatch(asset_id) is None:
            findings.append(
                MarkdownFinding(
                    "markdown-asset-id-invalid",
                    "error",
                    "Markdown image reference contains an invalid asset id.",
                    _line_of(canonical, match.start()),
                )
            )
            continue
        asset_ids.append(asset_id)

    footnote_refs = set(_FOOTNOTE_REF_RE.findall(canonical))
    footnote_defs = set(_FOOTNOTE_DEF_RE.findall(canonical))
    for missing in sorted(footnote_refs - footnote_defs):
        findings.append(
            MarkdownFinding(
                "markdown-footnote-definition-missing",
                "error",
                f"Footnote reference has no definition: {missing}",
            )
        )
    for unused in sorted(footnote_defs - footnote_refs):
        findings.append(
            MarkdownFinding(
                "markdown-footnote-definition-unused",
                "warning",
                f"Footnote definition is not referenced: {unused}",
            )
        )

    inspection = MarkdownInspection(
        word_count=len(_WORD_RE.findall(canonical)),
        heading_count=len(heading_levels),
        maximum_heading_level=max(heading_levels, default=0),
        image_count=len(image_targets),
        link_count=len(_LINK_RE.findall(canonical)),
        footnote_count=len(footnote_refs),
        list_count=len(_LIST_RE.findall(canonical)),
        scene_break_count=scene_break_count,
        page_break_count=page_break_count,
        asset_ids=tuple(asset_ids),
    )
    return MarkdownResult(
        canonical_markdown=canonical,
        findings=tuple(findings),
        inspection=inspection,
    )
