from __future__ import annotations

from app.utils.text import normalise_markdown


def structural_cleanup(markdown: str) -> str:
    """Usability-first structural cleanup.

    It is intentionally conservative. No AI. No content invention.
    """

    return normalise_markdown(markdown)
