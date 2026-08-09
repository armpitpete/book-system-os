from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.asset_ui import router as asset_ui_router
from app.api.auth import api_key_required
from app.api.revision_packages import router as revision_packages_router
from app.api.revision_ui_router import router as revision_ui_router
from app.api.revisions import router as revisions_router
from app.api.ui import router as dashboard_router
from app.services.author_assets import AuthorAssetError
from app.services.job_queue import create_job, get_job, read_status
from app.services.manuscript_validation import (
    ValidationServiceError,
    validate_manuscript,
)
from app.services.publish_plan import build_publish_dry_run
from app.services.readiness_guard import readiness_report
from app.services.resource_limits import RequestBodyLimitMiddleware, ResourceLimitError
from app.services.revision_studio import RevisionStudioError
from app.services.security import SecurityMiddleware
from app.version import APP_VERSION

app = FastAPI(title="Book System OS", version=APP_VERSION)
# Security may inspect bounded form bodies. Add it first so the existing request
# body limiter remains the outer middleware and rejects oversized bodies before
# authentication, CSRF parsing or job creation.
app.add_middleware(SecurityMiddleware)
app.add_middleware(RequestBodyLimitMiddleware)
app.include_router(dashboard_router)
app.include_router(asset_ui_router)
app.include_router(revision_ui_router)
app.include_router(revisions_router)
app.include_router(revision_packages_router)


@app.exception_handler(ResourceLimitError)
async def resource_limit_error(
    _request: Request,
    exc: ResourceLimitError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


@app.exception_handler(AuthorAssetError)
async def author_asset_error(
    _request: Request,
    exc: AuthorAssetError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


@app.exception_handler(ValidationServiceError)
async def validation_service_error(
    _request: Request,
    exc: ValidationServiceError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


@app.exception_handler(RevisionStudioError)
async def revision_studio_error(
    _request: Request,
    exc: RevisionStudioError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


class BookSubmitRequest(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: str = Field(min_length=1)


class BookValidateRequest(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: str


class BookPublishDryRunRequest(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: str


class ValidationFindingResponse(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    location: dict[str, int] | None = None


class ValidationSummaryResponse(BaseModel):
    request_title: str
    source_bytes: int
    normalised_bytes: int
    normalisation_changed: bool
    metadata_fields: list[str]
    block_count: int
    heading_count: int
    level_one_heading_count: int
    maximum_heading_level: int
    image_count: int
    table_count: int
    footnote_count: int
    list_count: int
    raw_content_count: int
    internal_link_count: int = Field(ge=0)
    broken_internal_link_count: int = Field(ge=0)


class BookValidateResponse(BaseModel):
    valid: bool
    errors: list[ValidationFindingResponse]
    warnings: list[ValidationFindingResponse]
    summary: ValidationSummaryResponse
    contract_version: Literal["0.2"]


class PublishOutputResponse(BaseModel):
    key: Literal["pdf_standard", "pdf_nd", "epub", "docx"]
    filename: str
    media_type: str


class BookPublishDryRunResponse(BaseModel):
    publishable: bool
    validation: BookValidateResponse
    outputs: list[PublishOutputResponse]
    source_bytes: int
    source_sha256: str
    job_state: Literal["production"]
    rendering_attempted: Literal[False]
    job_created: Literal[False]
    contract_version: Literal["0.2"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> JSONResponse:
    report = readiness_report()
    status_code = 200 if report["ready"] else 503
    return JSONResponse(status_code=status_code, content=report)


@app.get("/api/v1/status")
def api_v1_status() -> dict:
    return {
        "ok": True,
        "gateway": "publish.toiletrage.co.uk",
        "service": "book-system-os",
        "version": APP_VERSION,
        "routes_enabled": ["book-system", "author-assets", "revision-studio"],
        "write_enabled": True,
        "implemented": [
            "GET /health",
            "GET /ready",
            "GET /api/v1/status",
            "POST /api/v1/validate",
            "POST /api/v1/publish/dry-run",
            "POST /api/submit",
            "GET /api/jobs/{job_id}",
            "GET /assets",
            "POST /assets",
            "GET /assets/{asset_id}",
            "POST /assets/{asset_id}/configure",
            "GET /assets/{asset_id}/preview",
            "GET /revisions",
            "GET /revisions/{document_id}",
            "GET /revisions/{document_id}/proposals/{proposal_id}",
            "GET /revisions/{document_id}/history",
            "GET /revisions/{document_id}/package",
            "POST /api/v1/revisions/documents",
            "GET /api/v1/revisions/documents/{document_id}",
            "POST /api/v1/revisions/documents/{document_id}/proposals",
            "GET /api/v1/revisions/documents/{document_id}/proposals",
            "GET /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}",
            "GET /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}/compare",
            "POST /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}/decision",
            "GET /api/v1/revisions/documents/{document_id}/history",
            "GET /api/v1/revisions/documents/{document_id}/package",
            "POST /api/v1/revisions/package/verify",
        ],
        "not_yet_implemented": [
            "POST /api/v1/publish",
            "GET /api/v1/publish/{publish_id}",
            "GET /api/v1/publishes",
            "POST /api/v1/publish/{publish_id}/retry",
        ],
    }


@app.post(
    "/api/v1/validate",
    dependencies=[Depends(api_key_required)],
    response_model=BookValidateResponse,
)
def api_validate(payload: BookValidateRequest) -> dict[str, object]:
    return validate_manuscript(title=payload.title, markdown=payload.content)


@app.post(
    "/api/v1/publish/dry-run",
    dependencies=[Depends(api_key_required)],
    response_model=BookPublishDryRunResponse,
)
def api_publish_dry_run(payload: BookPublishDryRunRequest) -> dict[str, object]:
    return build_publish_dry_run(title=payload.title, markdown=payload.content)


@app.post("/api/submit", dependencies=[Depends(api_key_required)])
def api_submit(payload: BookSubmitRequest) -> dict[str, str]:
    job_id, _ = create_job(
        title=payload.title,
        markdown=payload.content,
        state="production",
    )
    return {"job_id": job_id, "status": "queued", "state": "production"}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(api_key_required)])
def api_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return read_status(job)
