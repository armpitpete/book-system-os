from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import api_key_required
from app.api.ui import router as ui_router
from app.services.job_queue import create_job, get_job, read_status

app = FastAPI(title="Book System OS", version="0.1.0")
app.include_router(ui_router)


class BookSubmitRequest(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: str = Field(min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/submit", dependencies=[Depends(api_key_required)])
def api_submit(payload: BookSubmitRequest) -> dict[str, str]:
    job_id, _ = create_job(title=payload.title, markdown=payload.content)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(api_key_required)])
def api_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return read_status(job)
