from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from app.publication.markdown_contract import inspect_markdown
from app.publication.model import (
    AssetPlacement,
    BindingIntent,
    BookPublication,
    ChapterStart,
    ContentRole,
    PageMode,
    TargetMedium,
    TrimSize,
)


class FeasibilityStatus(str, Enum):
    PASS = "PASS"
    CAUTION = "CAUTION"
    REJECT = "REJECT"


@dataclass(frozen=True)
class FeasibilityFinding:
    code: str
    level: str
    message: str


@dataclass(frozen=True)
class FeasibilityResult:
    status: FeasibilityStatus
    estimated_pages: int
    minimum_plausible_pages: int
    word_count: int
    findings: tuple[FeasibilityFinding, ...]


_WORDS_PER_PAGE: dict[TrimSize, tuple[int, int]] = {
    TrimSize.A7: (110, 180),
    TrimSize.A6: (180, 300),
    TrimSize.A5: (300, 475),
    TrimSize.A4: (480, 750),
}

_TRIM_AREA_MM2: dict[TrimSize, float] = {
    TrimSize.A7: 74 * 105,
    TrimSize.A6: 105 * 148,
    TrimSize.A5: 148 * 210,
    TrimSize.A4: 210 * 297,
}


def _capacity(publication: BookPublication) -> tuple[int, int]:
    intent = publication.intent
    if intent.trim_size in _WORDS_PER_PAGE:
        return _WORDS_PER_PAGE[intent.trim_size]
    assert intent.custom_width_mm is not None
    assert intent.custom_height_mm is not None
    area = intent.custom_width_mm * intent.custom_height_mm
    a5_area = _TRIM_AREA_MM2[TrimSize.A5]
    scale = max(0.2, min(4.0, area / a5_area))
    target = max(60, round(_WORDS_PER_PAGE[TrimSize.A5][0] * scale))
    hard_max = max(target + 20, round(_WORDS_PER_PAGE[TrimSize.A5][1] * scale))
    return target, hard_max


def assess_feasibility(publication: BookPublication) -> FeasibilityResult:
    findings: list[FeasibilityFinding] = []
    inspections = [inspect_markdown(unit.markdown).inspection for unit in publication.content_units]
    word_count = sum(item.word_count for item in inspections)
    page_breaks = sum(item.page_break_count for item in inspections)

    target_wpp, hard_max_wpp = _capacity(publication)

    fixed_page_roles = {
        ContentRole.TITLE_PAGE,
        ContentRole.COPYRIGHT,
        ContentRole.DEDICATION,
        ContentRole.CONTENTS,
        ContentRole.BLANK_PAGE,
    }
    structural_pages = sum(
        unit.role in fixed_page_roles for unit in publication.content_units
    )
    full_page_images = sum(
        asset.placement == AssetPlacement.FULL_PAGE for asset in publication.assets
    )
    cover_assets = sum(
        asset.placement == AssetPlacement.COVER for asset in publication.assets
    )
    if cover_assets > 1:
        findings.append(
            FeasibilityFinding(
                "multiple-cover-assets",
                "caution",
                "More than one asset is marked as the publication cover.",
            )
        )

    chapter_count = sum(
        unit.role == ContentRole.CHAPTER for unit in publication.content_units
    )
    recto_allowance = 0
    if (
        publication.intent.chapter_start == ChapterStart.RECTO
        and publication.intent.page_mode == PageMode.FACING
        and chapter_count > 1
    ):
        recto_allowance = (chapter_count - 1 + 1) // 2

    estimated_text_pages = math.ceil(word_count / target_wpp) if word_count else 0
    minimum_text_pages = math.ceil(word_count / hard_max_wpp) if word_count else 0
    overhead = structural_pages + full_page_images + page_breaks + recto_allowance
    estimated_pages = max(1, estimated_text_pages + overhead)
    minimum_pages = max(1, minimum_text_pages + overhead)

    fixed = publication.intent.fixed_page_count
    if fixed is not None:
        if (
            publication.intent.binding == BindingIntent.SADDLE_STITCH
            and fixed % 4 != 0
        ):
            findings.append(
                FeasibilityFinding(
                    "saddle-stitch-page-count-invalid",
                    "reject",
                    "A fixed saddle-stitched publication must have a page count divisible by four.",
                )
            )
        if minimum_pages > fixed:
            findings.append(
                FeasibilityFinding(
                    "fixed-page-capacity-exceeded",
                    "reject",
                    (
                        f"At least {minimum_pages} pages are plausibly required for "
                        f"{word_count} words and declared page-consuming content; "
                        f"the fixed budget is {fixed} pages."
                    ),
                )
            )
        elif estimated_pages > fixed:
            findings.append(
                FeasibilityFinding(
                    "fixed-page-capacity-tight",
                    "caution",
                    (
                        f"The normal estimate is {estimated_pages} pages for a fixed "
                        f"{fixed}-page budget. Composition may require unusually dense typography."
                    ),
                )
            )
        elif fixed > max(estimated_pages * 4, estimated_pages + 32):
            findings.append(
                FeasibilityFinding(
                    "fixed-page-capacity-sparse",
                    "caution",
                    "The fixed page budget is much larger than the current content estimate.",
                )
            )

    if publication.intent.target_medium == TargetMedium.DIGITAL:
        if publication.intent.bleed_mm:
            findings.append(
                FeasibilityFinding(
                    "digital-bleed-unused",
                    "info",
                    "Bleed is declared for a digital-only publication and will not normally be used.",
                )
            )
        if publication.intent.binding != BindingIntent.NONE:
            findings.append(
                FeasibilityFinding(
                    "digital-binding-unused",
                    "info",
                    "Binding intent is declared for a digital-only publication.",
                )
            )

    if any(item.level == "reject" for item in findings):
        status = FeasibilityStatus.REJECT
    elif any(item.level == "caution" for item in findings):
        status = FeasibilityStatus.CAUTION
    else:
        status = FeasibilityStatus.PASS

    return FeasibilityResult(
        status=status,
        estimated_pages=estimated_pages,
        minimum_plausible_pages=minimum_pages,
        word_count=word_count,
        findings=tuple(findings),
    )
