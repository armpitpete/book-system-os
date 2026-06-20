from __future__ import annotations

import re


def normalise_markdown(text: str) -> str:
    """Small deterministic cleanup before export.

    This does not rewrite meaning. It only normalises line endings,
    trims trailing whitespace, and reduces excessive blank lines.
    """

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines).strip() + "\n"
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text
