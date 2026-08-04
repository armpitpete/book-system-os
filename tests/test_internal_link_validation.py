from __future__ import annotations

import shutil

import pytest

from app.services import manuscript_validation


def link(target: str) -> dict[str, object]:
    return {
        "t": "Link",
        "c": [
            ["", [], []],
            [{"t": "Str", "c": target or "empty"}],
            [target, ""],
        ],
    }


def internal_link_ast() -> dict[str, object]:
    return {
        "pandoc-api-version": [1, 23, 1],
        "meta": {
            "title": {"t": "MetaString", "c": "Internal links"},
            "lang": {"t": "MetaString", "c": "en-GB"},
        },
        "blocks": [
            {
                "t": "Header",
                "c": [1, ["opening", [], []], [{"t": "Str", "c": "Opening"}]],
            },
            {
                "t": "Div",
                "c": [
                    ["panel", [], []],
                    [
                        {
                            "t": "Para",
                            "c": [
                                {
                                    "t": "Span",
                                    "c": [
                                        ["café", [], []],
                                        [{"t": "Str", "c": "Café"}],
                                    ],
                                }
                            ],
                        }
                    ],
                ],
            },
            {
                "t": "Para",
                "c": [
                    link("#opening"),
                    {"t": "Space"},
                    link("#panel"),
                    {"t": "Space"},
                    link("#caf%C3%A9"),
                    {"t": "Space"},
                    link("#missing-section"),
                    {"t": "Space"},
                    link("#missing-section"),
                    {"t": "Space"},
                    link("#"),
                    {"t": "Space"},
                    link("https://example.invalid/#missing-section"),
                ],
            },
        ],
    }


def test_internal_link_analysis_is_warning_only_and_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = internal_link_ast()
    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (document, False),
    )

    first = manuscript_validation.validate_manuscript(
        title="Internal links",
        markdown="# Opening\n",
    )
    second = manuscript_validation.validate_manuscript(
        title="Internal links",
        markdown="# Opening\n",
    )

    assert first == second
    assert first["valid"] is True
    assert first["errors"] == []

    findings = [
        finding
        for finding in first["warnings"]
        if finding["code"] == "broken-internal-link"
    ]
    assert findings == [
        {
            "code": "broken-internal-link",
            "severity": "warning",
            "message": "Internal link target was not found: #missing-section",
        }
    ]

    summary = first["summary"]
    assert summary["internal_link_count"] == 5
    assert summary["broken_internal_link_count"] == 2
    assert first["contract_version"] == "0.2"


def test_real_pandoc_identifiers_and_encoded_fragments_are_supported() -> None:
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is required for the real internal-link validation test")

    result = manuscript_validation.validate_manuscript(
        title="Internal links",
        markdown=(
            "---\n"
            "title: Internal links\n"
            "lang: en-GB\n"
            "---\n\n"
            "# Opening {#opening}\n\n"
            "[Café target]{#café}\n\n"
            "[Valid](#opening)\n\n"
            "[Encoded valid](#caf%C3%A9)\n\n"
            "[Broken](#absent)\n"
        ),
    )

    assert result["valid"] is True
    findings = [
        finding
        for finding in result["warnings"]
        if finding["code"] == "broken-internal-link"
    ]
    assert findings == [
        {
            "code": "broken-internal-link",
            "severity": "warning",
            "message": "Internal link target was not found: #absent",
        }
    ]
    assert result["summary"]["internal_link_count"] == 3
    assert result["summary"]["broken_internal_link_count"] == 1


def test_empty_and_parse_error_summaries_include_zero_link_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = manuscript_validation.validate_manuscript(title="Empty", markdown=" \n")
    assert empty["summary"]["internal_link_count"] == 0
    assert empty["summary"]["broken_internal_link_count"] == 0

    monkeypatch.setattr(
        manuscript_validation,
        "_parse_with_pandoc",
        lambda _markdown: (None, False),
    )
    malformed = manuscript_validation.validate_manuscript(
        title="Malformed",
        markdown="# Not parsed\n",
    )
    assert malformed["summary"]["internal_link_count"] == 0
    assert malformed["summary"]["broken_internal_link_count"] == 0
