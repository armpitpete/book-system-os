from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from app.api.auth import api_key_required
from app.services.revision_package import (
    build_revision_package,
    verify_revision_package,
)

router = APIRouter(
    prefix="/api/v1/revisions",
    tags=["Revision Studio packages"],
    dependencies=[Depends(api_key_required)],
)


@router.get("/documents/{document_id}/package")
def api_download_revision_package(document_id: str) -> Response:
    package = build_revision_package(document_id)
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "X-Content-SHA256": package.sha256,
            "X-Revision-Package-Version": "0.1",
        },
    )


@router.post("/package/verify")
async def api_verify_revision_package(
    package: UploadFile = File(...),
) -> dict:
    content = await package.read()
    return verify_revision_package(content)
