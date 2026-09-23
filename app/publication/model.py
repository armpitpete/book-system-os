from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "publication-model/v0.1"
_STABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublicationType(str, Enum):
    BOOK = "book"


class Matter(str, Enum):
    FRONT = "front"
    BODY = "body"
    BACK = "back"


class ContentRole(str, Enum):
    TITLE_PAGE = "title_page"
    COPYRIGHT = "copyright"
    DEDICATION = "dedication"
    EPIGRAPH = "epigraph"
    CONTENTS = "contents"
    PREFACE = "preface"
    INTRODUCTION = "introduction"
    PART = "part"
    CHAPTER = "chapter"
    SECTION = "section"
    NOTES = "notes"
    BIBLIOGRAPHY = "bibliography"
    APPENDIX = "appendix"
    ACKNOWLEDGEMENTS = "acknowledgements"
    ABOUT_AUTHOR = "about_author"
    BLANK_PAGE = "blank_page"


class AssetPlacement(str, Enum):
    INLINE = "inline"
    BLOCK = "block"
    FULL_PAGE = "full_page"
    COVER = "cover"


class TrimSize(str, Enum):
    A7 = "A7"
    A6 = "A6"
    A5 = "A5"
    A4 = "A4"
    CUSTOM = "custom"


class Orientation(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class BindingIntent(str, Enum):
    NONE = "none"
    SADDLE_STITCH = "saddle_stitch"
    PERFECT_BOUND = "perfect_bound"
    CASE_BOUND = "case_bound"
    COIL = "coil"


class PageMode(str, Enum):
    SINGLE = "single_pages"
    FACING = "facing_pages"


class TargetMedium(str, Enum):
    PRINT = "print"
    DIGITAL = "digital"
    BOTH = "both"


class ColorIntent(str, Enum):
    MONOCHROME = "monochrome"
    GRAYSCALE = "grayscale"
    COLOR = "color"


class ChapterStart(str, Enum):
    ANY = "any"
    RECTO = "recto"


class Identifier(FrozenModel):
    scheme: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=128)


class SourceProvenance(FrozenModel):
    source_path: str = Field(min_length=1, max_length=1024)
    source_sha256: str
    canonical_sha256: str
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @field_validator("source_sha256", "canonical_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if _SHA256_RE.fullmatch(value) is None:
            raise ValueError("provenance-sha256-invalid")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> SourceProvenance:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("provenance-line-range-invalid")
        return self


class Asset(FrozenModel):
    id: str
    source_path: str = Field(min_length=1, max_length=1024)
    media_type: str = Field(min_length=3, max_length=128)
    width_px: int | None = Field(default=None, gt=0)
    height_px: int | None = Field(default=None, gt=0)
    alt_text: str | None = Field(default=None, max_length=1000)
    caption: str | None = Field(default=None, max_length=2000)
    placement: AssetPlacement = AssetPlacement.BLOCK

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if _STABLE_ID_RE.fullmatch(value) is None:
            raise ValueError("asset-id-invalid")
        return value


class PublicationMetadata(FrozenModel):
    title: str = Field(max_length=300)
    subtitle: str | None = Field(default=None, max_length=300)
    creators: tuple[str, ...] = Field(min_length=1)
    language: str = Field(default="en-GB", min_length=2, max_length=35)
    status: str | None = Field(default=None, max_length=64)
    identifiers: tuple[Identifier, ...] = ()

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("publication-title-required")
        return cleaned

    @field_validator("creators")
    @classmethod
    def clean_creators(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("publication-creator-invalid")
        return cleaned

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if _LANGUAGE_TAG_RE.fullmatch(value) is None:
            raise ValueError("publication-language-invalid")
        return value


class ContentUnit(FrozenModel):
    id: str
    role: ContentRole
    matter: Matter
    title: str | None = Field(default=None, max_length=300)
    parent_id: str | None = None
    markdown: str = ""
    provenance: SourceProvenance
    asset_ids: tuple[str, ...] = ()

    @field_validator("id", "parent_id")
    @classmethod
    def validate_id(cls, value: str | None) -> str | None:
        if value is not None and _STABLE_ID_RE.fullmatch(value) is None:
            raise ValueError("content-unit-id-invalid")
        return value

    @field_validator("asset_ids")
    @classmethod
    def validate_asset_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("content-unit-asset-duplicate")
        if any(_STABLE_ID_RE.fullmatch(item) is None for item in value):
            raise ValueError("content-unit-asset-id-invalid")
        return value


class PublicationIntent(FrozenModel):
    trim_size: TrimSize = TrimSize.A5
    custom_width_mm: float | None = Field(default=None, gt=0, le=1000)
    custom_height_mm: float | None = Field(default=None, gt=0, le=1000)
    orientation: Orientation = Orientation.PORTRAIT
    binding: BindingIntent = BindingIntent.PERFECT_BOUND
    page_mode: PageMode = PageMode.FACING
    bleed_mm: float = Field(default=3.0, ge=0, le=25)
    target_medium: TargetMedium = TargetMedium.PRINT
    color_intent: ColorIntent = ColorIntent.MONOCHROME
    fixed_page_count: int | None = Field(default=None, ge=1, le=5000)
    typography_intent: tuple[str, ...] = ()
    style_roles: tuple[str, ...] = ()
    chapter_start: ChapterStart = ChapterStart.ANY

    @model_validator(mode="after")
    def validate_custom_trim(self) -> PublicationIntent:
        custom = self.trim_size == TrimSize.CUSTOM
        if custom != (
            self.custom_width_mm is not None and self.custom_height_mm is not None
        ):
            raise ValueError("publication-custom-trim-invalid")
        return self


_ROLE_MATTER: dict[ContentRole, set[Matter]] = {
    ContentRole.TITLE_PAGE: {Matter.FRONT},
    ContentRole.COPYRIGHT: {Matter.FRONT},
    ContentRole.DEDICATION: {Matter.FRONT},
    ContentRole.EPIGRAPH: {Matter.FRONT, Matter.BODY},
    ContentRole.CONTENTS: {Matter.FRONT},
    ContentRole.PREFACE: {Matter.FRONT},
    ContentRole.INTRODUCTION: {Matter.FRONT, Matter.BODY},
    ContentRole.PART: {Matter.BODY},
    ContentRole.CHAPTER: {Matter.BODY},
    ContentRole.SECTION: {Matter.BODY},
    ContentRole.NOTES: {Matter.BACK},
    ContentRole.BIBLIOGRAPHY: {Matter.BACK},
    ContentRole.APPENDIX: {Matter.BACK},
    ContentRole.ACKNOWLEDGEMENTS: {Matter.BACK},
    ContentRole.ABOUT_AUTHOR: {Matter.BACK},
    ContentRole.BLANK_PAGE: {Matter.FRONT, Matter.BODY, Matter.BACK},
}

_ALLOWED_PARENT_ROLES: dict[ContentRole, set[ContentRole]] = {
    ContentRole.CHAPTER: {ContentRole.PART},
    ContentRole.SECTION: {ContentRole.CHAPTER, ContentRole.SECTION},
}

_AUTO_OR_BLANK_ROLES = {
    ContentRole.TITLE_PAGE,
    ContentRole.COPYRIGHT,
    ContentRole.CONTENTS,
    ContentRole.BLANK_PAGE,
}


class Publication(FrozenModel):
    schema_version: Literal["publication-model/v0.1"] = SCHEMA_VERSION
    id: str
    publication_type: PublicationType
    metadata: PublicationMetadata
    content_units: tuple[ContentUnit, ...]
    assets: tuple[Asset, ...] = ()
    intent: PublicationIntent

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if _STABLE_ID_RE.fullmatch(value) is None:
            raise ValueError("publication-id-invalid")
        return value

    @model_validator(mode="after")
    def validate_references_and_order(self) -> Publication:
        unit_ids = [unit.id for unit in self.content_units]
        asset_ids = [asset.id for asset in self.assets]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("content-unit-id-duplicate")
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset-id-duplicate")

        assets = set(asset_ids)
        units_by_id: dict[str, ContentUnit] = {}
        seen_matter_rank = 0
        ranks = {Matter.FRONT: 0, Matter.BODY: 1, Matter.BACK: 2}

        for unit in self.content_units:
            if unit.matter not in _ROLE_MATTER[unit.role]:
                raise ValueError(f"content-role-matter-invalid:{unit.id}")
            rank = ranks[unit.matter]
            if rank < seen_matter_rank:
                raise ValueError(f"content-matter-order-invalid:{unit.id}")
            seen_matter_rank = max(seen_matter_rank, rank)
            missing_assets = sorted(set(unit.asset_ids) - assets)
            if missing_assets:
                raise ValueError(
                    f"content-asset-reference-missing:{unit.id}:{','.join(missing_assets)}"
                )
            if unit.role not in _AUTO_OR_BLANK_ROLES and not unit.markdown.strip():
                raise ValueError(f"content-unit-empty:{unit.id}")
            if unit.role == ContentRole.BLANK_PAGE and unit.markdown.strip():
                raise ValueError(f"blank-page-content-invalid:{unit.id}")

            if unit.parent_id is not None:
                parent = units_by_id.get(unit.parent_id)
                if parent is None:
                    raise ValueError(f"content-parent-order-invalid:{unit.id}")
                allowed = _ALLOWED_PARENT_ROLES.get(unit.role, set())
                if parent.role not in allowed:
                    raise ValueError(f"content-parent-role-invalid:{unit.id}")
                if parent.matter != unit.matter:
                    raise ValueError(f"content-parent-matter-invalid:{unit.id}")
            elif unit.role == ContentRole.SECTION:
                raise ValueError(f"content-section-parent-required:{unit.id}")

            units_by_id[unit.id] = unit

        singleton_roles = {
            ContentRole.TITLE_PAGE,
            ContentRole.COPYRIGHT,
            ContentRole.CONTENTS,
        }
        for role in singleton_roles:
            if sum(unit.role == role for unit in self.content_units) > 1:
                raise ValueError(f"content-singleton-role-duplicate:{role.value}")
        return self

    def canonical_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=False)

    def canonical_json(self) -> str:
        return json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def canonical_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class BookPublication(Publication):
    publication_type: Literal[PublicationType.BOOK] = PublicationType.BOOK

    @model_validator(mode="after")
    def validate_book_profile(self) -> BookPublication:
        body_roles = {ContentRole.PART, ContentRole.CHAPTER, ContentRole.SECTION}
        if not any(
            unit.matter == Matter.BODY and unit.role in body_roles
            for unit in self.content_units
        ):
            raise ValueError("book-body-required")
        return self
