from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.services.manuscript_validation import CONTRACT_VERSION, validate_manuscript


@dataclass(frozen=True)
class PublishOutputSpec:
    key: str
    filename: str
    media_type: str


PUBLISH_OUTPUTS: tuple[PublishOutputSpec, ...] = (
    PublishOutputSpec(
        key="pdf_standard",
        filename="book-standard.pdf",
        media_type="application/pdf",
    ),
    PublishOutputSpec(
        key="pdf_nd",
        filename="book-nd.pdf",
        media_type="application/pdf",
    ),
    PublishOutputSpec(
        key="epub",
        filename="book.epub",
        media_type="application/epub+zip",
    ),
    PublishOutputSpec(
        key="docx",
        filename="book.docx",
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    ),
)


def publish_output_plan() -> list[dict[str, str]]:
    return [
        {
            "key": output.key,
            "filename": output.filename,
            "media_type": output.media_type,
        }
        for output in PUBLISH_OUTPUTS
    ]


def build_publish_dry_run(*, title: str, markdown: str) -> dict[str, object]:
    source = markdown.encode("utf-8")
    validation = validate_manuscript(title=title, markdown=markdown)

    return {
        "publishable": validation["valid"],
        "validation": validation,
        "outputs": publish_output_plan(),
        "source_bytes": len(source),
        "source_sha256": sha256(source).hexdigest(),
        "job_state": "production",
        "rendering_attempted": False,
        "job_created": False,
        "contract_version": CONTRACT_VERSION,
    }
