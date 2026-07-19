from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.api.ui import dashboard as existing_dashboard
from app.services.job_queue import create_job

router = APIRouter(dependencies=[Depends(dashboard_auth)])

DASHBOARD_JOB_STATES = {"test", "production"}
JOB_TYPE_FIELD = """
          <p><label>Job type<br>
            <select name="state">
              <option value="test" selected>Test — default for manual checks</option>
              <option value="production">Production — retained as a real publication job</option>
            </select>
          </label></p>
"""
MARKDOWN_FIELD = "          <p><label>Markdown<br><textarea"


@router.get("/", response_class=HTMLResponse)
def dashboard(
    show_test: str = Query("1"),
    show_failed: str = Query("1"),
    show_archived: str = Query("0"),
) -> HTMLResponse:
    response = existing_dashboard(
        show_test=show_test,
        show_failed=show_failed,
        show_archived=show_archived,
    )
    body = response.body.decode(response.charset or "utf-8")
    if 'name="state"' not in body:
        body = body.replace(MARKDOWN_FIELD, JOB_TYPE_FIELD + MARKDOWN_FIELD, 1)
    return HTMLResponse(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
    )


@router.post("/submit-form")
def submit_form(
    title: str = Form("Untitled"),
    content: str = Form(...),
    state: str = Form("test"),
) -> RedirectResponse:
    requested_state = state.strip().lower()
    if requested_state not in DASHBOARD_JOB_STATES:
        raise HTTPException(status_code=400, detail="Invalid dashboard job type")

    create_job(title=title, markdown=content, state=requested_state)
    return RedirectResponse(url="/", status_code=303)
