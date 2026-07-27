from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.auth import api_key_required
from app.api.ui import router as dashboard_router
from app.services.job_queue import create_job, get_job, read_status
from app.services.readiness_guard import readiness_report
from app.services.resource_limits import RequestBodyLimitMiddleware, ResourceLimitError
from app.services.security import SecurityMiddleware
from app.version import APP_VERSION

app = FastAPI(title="Book System OS", version=APP_VERSION)
# Security may inspect bounded form bodies. Add it first so the existing request
# body limiter remains the outer middleware and rejects oversized bodies before
# authentication, CSRF parsing or job creation.
app.add_middleware(SecurityMiddleware)
app.add_middleware(RequestBodyLimitMiddleware)
app.include_router(dashboard_router)


@app.exception_handler(ResourceLimitError)
async def resource_limit_error(
    _request: Request,
    exc: ResourceLimitError,
) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload())


class BookSubmitRequest(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: str = Field(min_length=1)


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
        "routes_enabled": ["book-system"],
        "write_enabled": True,
        "implemented": [
            "GET /health",
            "GET /ready",
            "GET /api/v1/status",
            "POST /api/submit",
            "GET /api/jobs/{job_id}",
        ],
        "not_yet_implemented": [
            "POST /api/v1/validate",
            "POST /api/v1/publish/dry-run",
            "POST /api/v1/publish",
            "GET /api/v1/publish/{publish_id}",
            "GET /api/v1/publishes",
            "POST /api/v1/publish/{publish_id}/retry",
        ],
    }


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
