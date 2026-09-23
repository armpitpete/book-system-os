from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.publication.builder import PublicationRejected, assess_book, build_book_or_raise
from app.publication.feasibility import FeasibilityStatus
from app.publication.markdown_contract import canonicalize_markdown, inspect_markdown
from app.publication.model import BookPublication, PublicationIntent, TrimSize
from app.services.publish_plan import PUBLISH_OUTPUTS

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "publication_model" / "cases.json"


def metadata(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "title": "Test Book",
        "creators": ["Merrin W. Dream"],
        "language": "en-GB",
    }
    value.update(overrides)
    return value


def intent(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "trim_size": "A5",
        "orientation": "portrait",
        "binding": "perfect_bound",
        "page_mode": "facing_pages",
        "bleed_mm": 3,
        "target_medium": "print",
        "color_intent": "monochrome",
        "chapter_start": "any",
    }
    value.update(overrides)
    return value


def chapter(
    markdown: str = "# Chapter One\n\nBody text.\n",
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "ch1",
        "role": "chapter",
        "matter": "body",
        "title": "Chapter One",
        "source_path": "chapters/ch1.md",
        "markdown": markdown,
    }
    value.update(overrides)
    return value


def codes(result: object) -> set[str]:
    return {item.code for item in result.findings}  # type: ignore[attr-defined]


def test_minimal_book_builds_to_renderer_independent_model() -> None:
    result = assess_book(
        publication_id="test-book",
        metadata=metadata(),
        content_units=[chapter()],
        intent=intent(),
    )

    assert result.accepted is True
    assert result.publication is not None
    assert result.publication.schema_version == "publication-model/v0.1"
    assert result.publication.publication_type.value == "book"
    assert result.feasibility is not None
    assert result.feasibility.status == FeasibilityStatus.PASS


def test_serialization_is_deterministic_and_round_trips() -> None:
    book = build_book_or_raise(
        publication_id="deterministic-book",
        metadata=metadata(),
        content_units=[chapter()],
        intent=intent(),
    )

    first = book.canonical_json()
    second = book.canonical_json()
    restored = BookPublication.model_validate_json(first)

    assert first == second
    assert restored == book
    assert restored.canonical_sha256() == book.canonical_sha256()
    assert list(json.loads(first)) == sorted(json.loads(first))


def test_source_provenance_preserves_source_and_canonical_hashes() -> None:
    source = "# One\r\n\r\nText without final newline"
    result = assess_book(
        publication_id="provenance-book",
        metadata=metadata(),
        content_units=[chapter(source)],
        intent=intent(),
    )

    assert result.publication is not None
    unit = result.publication.content_units[0]
    assert unit.markdown == "# One\n\nText without final newline\n"
    assert unit.provenance.source_sha256 != unit.provenance.canonical_sha256


def test_markdown_contract_accepts_supported_semantics() -> None:
    markdown = (
        "# Heading\n\n"
        "Paragraph with *emphasis*, **strong**, and [a link](https://example.test).\n\n"
        "> A block quote.\n\n"
        "- one\n- two\n\n"
        "![Diagram](asset:diagram)\n\n"
        "Claim.[^n1]\n\n[^n1]: Footnote.\n\n"
        "***\n\n"
        "<!-- bos:page-break -->\n"
    )

    result = inspect_markdown(markdown)

    assert result.valid is True
    assert result.inspection.heading_count == 1
    assert result.inspection.image_count == 1
    assert result.inspection.asset_ids == ("diagram",)
    assert result.inspection.footnote_count == 1
    assert result.inspection.list_count == 2
    assert result.inspection.scene_break_count == 1
    assert result.inspection.page_break_count == 1


@pytest.mark.parametrize(
    ("markdown", "expected_code"),
    [
        ("# One\n\n<div>raw</div>\n", "markdown-raw-html-unsupported"),
        ("# One\n\nA | B\n---|---\n1 | 2\n", "markdown-table-unsupported"),
        ("# One\n\n```python\nprint('x')\n```\n", "markdown-fenced-code-unsupported"),
        ("# One\n\n![Image](images/x.png)\n", "markdown-image-reference-not-asset"),
        ("---\ntitle: Embedded\n---\n\n# One\n", "markdown-embedded-metadata"),
    ],
)
def test_markdown_contract_rejects_unsupported_constructs(
    markdown: str,
    expected_code: str,
) -> None:
    result = inspect_markdown(markdown)

    assert result.valid is False
    assert expected_code in {item.code for item in result.findings}


def test_markdown_canonicalization_is_narrow_and_deterministic() -> None:
    assert canonicalize_markdown("A\r\nB\rC") == "A\nB\nC\n"
    assert canonicalize_markdown("A\n") == "A\n"


def test_content_matter_order_is_enforced() -> None:
    result = assess_book(
        publication_id="bad-order",
        metadata=metadata(),
        content_units=[
            {
                "id": "thanks",
                "role": "acknowledgements",
                "matter": "back",
                "source_path": "thanks.md",
                "markdown": "# Thanks\n\nThanks.\n",
            },
            chapter(),
        ],
        intent=intent(),
    )

    assert result.accepted is False
    assert "content-matter-order-invalid" in codes(result)


def test_nested_section_requires_parent_before_child() -> None:
    good = assess_book(
        publication_id="nested",
        metadata=metadata(),
        content_units=[
            chapter(),
            {
                "id": "sec1",
                "role": "section",
                "matter": "body",
                "parent_id": "ch1",
                "source_path": "chapters/ch1-sec1.md",
                "markdown": "## Detail\n\nMore.\n",
            },
        ],
        intent=intent(),
    )
    bad = assess_book(
        publication_id="orphan",
        metadata=metadata(),
        content_units=[
            {
                "id": "sec1",
                "role": "section",
                "matter": "body",
                "parent_id": "ch1",
                "source_path": "chapters/ch1-sec1.md",
                "markdown": "## Detail\n\nMore.\n",
            },
            chapter(),
        ],
        intent=intent(),
    )

    assert good.accepted is True
    assert bad.accepted is False
    assert "content-parent-order-invalid" in codes(bad)


def test_asset_reference_is_checked_against_declared_assets() -> None:
    missing = assess_book(
        publication_id="missing-asset",
        metadata=metadata(),
        content_units=[chapter("# One\n\n![Missing](asset:not-declared)\n")],
        intent=intent(),
    )
    present = assess_book(
        publication_id="present-asset",
        metadata=metadata(),
        assets=[
            {
                "id": "diagram",
                "source_path": "images/diagram.png",
                "media_type": "image/png",
                "width_px": 1200,
                "height_px": 800,
                "alt_text": "Diagram",
                "caption": "A diagram.",
            }
        ],
        content_units=[chapter("# One\n\n![Diagram](asset:diagram)\n")],
        intent=intent(),
    )

    assert missing.accepted is False
    assert "content-asset-reference-missing" in codes(missing)
    assert present.accepted is True


def test_asset_file_validation_is_bounded_to_asset_root() -> None:
    asset_root = FIXTURES.parent / "not-created-asset-root"
    missing = assess_book(
        publication_id="file-missing",
        metadata=metadata(),
        assets=[
            {
                "id": "diagram",
                "source_path": "images/diagram.png",
                "media_type": "image/png",
            }
        ],
        content_units=[chapter("# One\n\n![Diagram](asset:diagram)\n")],
        intent=intent(),
        asset_root=asset_root,
    )
    escaping = assess_book(
        publication_id="file-escape",
        metadata=metadata(),
        assets=[
            {
                "id": "diagram",
                "source_path": "../diagram.png",
                "media_type": "image/png",
            }
        ],
        content_units=[chapter("# One\n\n![Diagram](asset:diagram)\n")],
        intent=intent(),
        asset_root=asset_root,
    )

    assert "asset-file-missing" in codes(missing)
    assert "asset-path-outside-root" in codes(escaping)


def test_impossible_a7_90000_word_fixed_book_is_rejected() -> None:
    result = assess_book(
        publication_id="impossible",
        metadata=metadata(),
        content_units=[chapter("# One\n\n" + ("word " * 90_000))],
        intent=intent(
            trim_size="A7",
            binding="saddle_stitch",
            fixed_page_count=16,
        ),
    )

    assert result.accepted is False
    assert result.feasibility is not None
    assert result.feasibility.status == FeasibilityStatus.REJECT
    assert "fixed-page-capacity-exceeded" in codes(result)
    assert result.feasibility.minimum_plausible_pages > 16


def test_saddle_stitch_fixed_page_count_must_be_divisible_by_four() -> None:
    result = assess_book(
        publication_id="bad-signature",
        metadata=metadata(),
        content_units=[chapter()],
        intent=intent(
            trim_size="A6",
            binding="saddle_stitch",
            fixed_page_count=10,
        ),
    )

    assert result.accepted is False
    assert "saddle-stitch-page-count-invalid" in codes(result)


def test_custom_trim_requires_both_dimensions() -> None:
    with pytest.raises(ValidationError):
        PublicationIntent(trim_size=TrimSize.CUSTOM, custom_width_mm=120)

    value = PublicationIntent(
        trim_size=TrimSize.CUSTOM,
        custom_width_mm=120,
        custom_height_mm=180,
    )
    assert value.custom_width_mm == 120
    assert value.custom_height_mm == 180


def test_build_or_raise_stops_invalid_publication_before_renderer() -> None:
    with pytest.raises(PublicationRejected) as exc_info:
        build_book_or_raise(
            publication_id="rejected",
            metadata=metadata(),
            content_units=[chapter("![External](x.png)\n")],
            intent=intent(),
        )

    assert "markdown-image-reference-not-asset" in codes(exc_info.value.assessment)


def test_fixture_corpus_covers_required_phase1_cases() -> None:
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))
    names = {item["name"] for item in fixture["cases"]}

    assert names == {
        "minimal-one-chapter",
        "normal-multi-chapter",
        "front-matter",
        "back-matter",
        "images",
        "notes",
        "nested-sections",
        "short-chapbook",
        "fixed-page-publication",
        "impossible-a7-90000",
        "missing-asset",
        "malformed-metadata",
        "invalid-content-order",
    }


def test_fixture_corpus_has_expected_acceptance_results() -> None:
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        case_metadata = case.get("metadata", metadata())
        case_intent = intent(**case.get("intent", {}))
        units = case.get("units")
        repeat_words = case.get("repeat_words")
        if units is None:
            units = [
                chapter(
                    "# One\n\n" + ("word " * int(repeat_words or 20)),
                )
            ]

        result = assess_book(
            publication_id=f"fixture-{case['name']}",
            metadata=case_metadata,
            content_units=units,
            assets=case.get("assets", []),
            intent=case_intent,
        )

        assert result.accepted is case["expected_accepted"], case["name"]
        if "expected_code" in case:
            assert case["expected_code"] in codes(result), case["name"]


def test_phase1_does_not_change_current_four_output_contract() -> None:
    assert [item.key for item in PUBLISH_OUTPUTS] == [
        "pdf_standard",
        "pdf_nd",
        "epub",
        "docx",
    ]


def test_publication_package_has_no_legacy_renderer_dependency() -> None:
    publication_dir = ROOT / "app" / "publication"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in publication_dir.glob("*.py")
    ).lower()

    assert "subprocess" not in source
    assert "xelatex" not in source
    assert "pandoc" not in source
    assert "affinity" not in source


def test_current_v1_h08_markdown_requires_explicit_migration() -> None:
    legacy = (ROOT / "tests" / "fixtures" / "h08" / "representative.md").read_text(
        encoding="utf-8"
    )
    result = inspect_markdown(legacy)
    found = {item.code for item in result.findings}
    assert result.valid is False
    assert "markdown-embedded-metadata" in found
    assert "markdown-table-unsupported" in found
    assert "markdown-fenced-code-unsupported" in found
    assert "markdown-raw-html-unsupported" in found


def test_invalid_provenance_range_is_reported_not_raised() -> None:
    result = assess_book(
        publication_id="bad-provenance",
        metadata=metadata(),
        content_units=[
            chapter(line_start=10, line_end=2),
        ],
        intent=intent(),
    )

    assert result.accepted is False
    assert "provenance-line-range-invalid" in codes(result)
