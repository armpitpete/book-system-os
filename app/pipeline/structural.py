from __future__ import annotations

import re

from app.utils.text import normalise_markdown

_CHAPTER_LINK_RE = re.compile(r"\]\(\s*#(chapter-(\d+))\s*\)")
_H1_RE = re.compile(r"^#(?:[ \t]+\S|$)")
_EXPLICIT_ID_RE = re.compile(r"\{#([^\s}]+)(?:\s+[^}]*)?\}")
_TRAILING_ATTRIBUTE_RE = re.compile(r"\{[^}]*\}\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _fence_run(line: str) -> tuple[str, int, str] | None:
    match = _FENCE_RE.match(line)
    if match is None:
        return None
    run = match.group(1)
    return run[0], len(run), match.group(2)


def _repair_referenced_chapter_anchors(markdown: str) -> str:
    """Preserve referenced sequential chapter fragments without rewriting prose.

    A manuscript may intentionally link to stable fragments such as
    ``#chapter-02`` while leaving the matching H1 identifier for the production
    layer. Bind such a fragment only when its numeric ordinal maps to one real
    level-one heading, the exact fragment is actually referenced, and no
    conflicting explicit identifier is already present. Anything ambiguous is
    left untouched so validation can continue to report it.
    """

    lines = markdown.splitlines()
    h1_indexes: list[int] = []
    existing_ids: set[str] = set()
    referenced_by_ordinal: dict[int, set[str]] = {}
    active_fence: tuple[str, int] | None = None

    for index, line in enumerate(lines):
        fence = _fence_run(line)
        if active_fence is None:
            if fence is not None:
                active_fence = (fence[0], fence[1])
                continue
        else:
            if (
                fence is not None
                and fence[0] == active_fence[0]
                and fence[1] >= active_fence[1]
                and not fence[2].strip()
            ):
                active_fence = None
            continue

        existing_ids.update(match.group(1) for match in _EXPLICIT_ID_RE.finditer(line))

        if _H1_RE.match(line):
            h1_indexes.append(index)

        for match in _CHAPTER_LINK_RE.finditer(line):
            fragment = match.group(1)
            ordinal = int(match.group(2))
            referenced_by_ordinal.setdefault(ordinal, set()).add(fragment)

    for ordinal, fragments in referenced_by_ordinal.items():
        if len(fragments) != 1 or ordinal < 1 or ordinal > len(h1_indexes):
            continue
        fragment = next(iter(fragments))
        if fragment in existing_ids:
            continue

        line_index = h1_indexes[ordinal - 1]
        line = lines[line_index]
        if _TRAILING_ATTRIBUTE_RE.search(line) is not None:
            continue

        lines[line_index] = f"{line} {{#{fragment}}}"
        existing_ids.add(fragment)

    return "\n".join(lines) + "\n"


def structural_cleanup(markdown: str) -> str:
    """Usability-first structural cleanup.

    It is intentionally conservative. No AI. No content invention.
    """

    return _repair_referenced_chapter_anchors(normalise_markdown(markdown))
