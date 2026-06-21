from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.services.job_queue import JOB_STATES, create_job, get_job, list_jobs, read_status, set_job_state

router = APIRouter(dependencies=[Depends(dashboard_auth)])


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #f5f5f1; color: #20262c; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
    h1, h2, h3 {{ line-height: 1.15; }}
    .card {{ background: white; border: 1px solid #ddd9cc; border-radius: 14px; padding: 18px; margin: 16px 0; box-shadow: 0 1px 4px rgba(0,0,0,.04); }}
    textarea, input, select {{ width: 100%; box-sizing: border-box; padding: 12px; border: 1px solid #bbb6a7; border-radius: 10px; font: inherit; }}
    textarea {{ min-height: 320px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    button, .button {{ display: inline-block; background: #20262c; color: white; border: 0; border-radius: 10px; padding: 10px 14px; text-decoration: none; font-weight: 650; cursor: pointer; }}
    .secondary {{ background: #efeee8; color: #20262c; }}
    .muted {{ color: #60656c; }}
    .status {{ display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 0.9rem; background: #eee; }}
    .queued {{ background: #fff2c2; }} .running {{ background: #dbeafe; }} .done {{ background: #dcfce7; }} .failed {{ background: #fee2e2; }}
    .state {{ display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 0.9rem; background: #efeee8; }}
    .state.production {{ background: #e9edf5; }} .state.test {{ background: #fff7d6; }} .state.archived {{ background: #e5e7eb; }}
    code {{ background: #efeee8; padding: 2px 5px; border-radius: 5px; }}
  </style>
</head>
<body><main>{body}</main></body>
</html>""")


def status_badge(status: str) -> str:
    safe = html.escape(status or "unknown")
    cls = safe if safe in {"queued", "running", "done", "failed"} else ""
    return f'<span class="status {cls}">{safe}</span>'


def state_badge(state: str) -> str:
    safe = html.escape(state or "production")
    cls = safe if safe in {"test", "production", "archived"} else ""
    return f'<span class="state {cls}">{safe}</span>'


def job_state_controls(job_id: str, current_state: str) -> str:
    safe_job_id = quote(job_id, safe="")
    controls = []
    for target_state, label, button_class in (
        ("test", "Mark as test", "secondary"),
        ("production", "Mark as production", "secondary"),
        ("archived", "Archive", ""),
    ):
        controls.append(f"""
          <form method="post" action="/jobs/{safe_job_id}/state" style="display: inline-block; margin: 0 8px 8px 0;">
            <button class="{button_class}" type="submit" name="state" value="{target_state}">{label}</button>
          </form>
        """)

    return f"""
      <div class="card">
        <h2>Lifecycle</h2>
        <p class="muted">Current lifecycle state: {state_badge(current_state)}</p>
        {''.join(controls)}
      </div>
    """


def truthy_query(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "show"}


def selected_attr(current: bool, option: bool) -> str:
    return " selected" if current is option else ""


@router.get("/", response_class=HTMLResponse)
def dashboard(
    show_test: str = Query("1"),
    show_failed: str = Query("1"),
    show_archived: str = Query("0"),
) -> HTMLResponse:
    show_test_bool = truthy_query(show_test, default=True)
    show_failed_bool = truthy_query(show_failed, default=True)
    show_archived_bool = truthy_query(show_archived, default=False)

    cards = []
    for job in list_jobs():
        status = read_status(job)
        job_state = status.get("state", "production")
        job_status = status.get("status", "unknown")

        if job_state == "test" and not show_test_bool:
            continue
        if job_state == "archived" and not show_archived_bool:
            continue
        if job_status == "failed" and not show_failed_bool:
            continue

        job_id = html.escape(job.name)
        meta_title = "Untitled"
        meta = job / "metadata.json"
        if meta.exists():
            try:
                meta_title = json.loads(meta.read_text(encoding="utf-8")).get("title", "Untitled")
            except Exception:
                pass
        cards.append(f"""
        <div class="card">
          <h3>{html.escape(meta_title)}</h3>
          <p>{status_badge(job_status)} {state_badge(job_state)} <span class="muted">{job_id}</span></p>
          <p class="muted">Step: {html.escape(status.get('step', 'unknown'))} &mdash; {html.escape(status.get('message', ''))}</p>
          <p><a class="button" href="/jobs/{job_id}">Open job</a></p>
        </div>
        """)

        if len(cards) >= 30:
            break

    job_list = "\n".join(cards) if cards else '<p class="muted">No jobs match the current filters.</p>'

    return page("Publishing Dashboard", f"""
      <h1>Publishing Dashboard</h1>
      <p class="muted">Domain target: <code>publish.toiletrage.co.uk</code></p>
      <div class="card">
        <h2>Queue book build</h2>
        <form method="post" action="/submit-form">
          <p><label>Title<br><input name="title" value="A Book for Neurodivergent Minds"></label></p>
          <p><label>Markdown<br><textarea name="content" placeholder="# Title\n\nPaste Markdown here..."></textarea></label></p>
          <button type="submit">Queue book build</button>
        </form>
      </div>

      <div class="card">
        <h2>Job filters</h2>
        <form method="get" action="/">
          <p><label>Test jobs<br>
            <select name="show_test">
              <option value="1"{selected_attr(show_test_bool, True)}>Show</option>
              <option value="0"{selected_attr(show_test_bool, False)}>Hide</option>
            </select>
          </label></p>
          <p><label>Failed jobs<br>
            <select name="show_failed">
              <option value="1"{selected_attr(show_failed_bool, True)}>Show</option>
              <option value="0"{selected_attr(show_failed_bool, False)}>Hide</option>
            </select>
          </label></p>
          <p><label>Archived jobs<br>
            <select name="show_archived">
              <option value="0"{selected_attr(show_archived_bool, False)}>Hide</option>
              <option value="1"{selected_attr(show_archived_bool, True)}>Show</option>
            </select>
          </label></p>
          <button type="submit">Apply filters</button>
          <a class="button secondary" href="/">Reset</a>
        </form>
      </div>

      <h2>Jobs</h2>
      <p class="muted">Showing up to 30 jobs matching the current filters.</p>
      {job_list}
    """)


@router.post("/submit-form")
def submit_form(title: str = Form("Untitled"), content: str = Form(...)) -> RedirectResponse:
    create_job(title=title, markdown=content)
    return RedirectResponse(url="/", status_code=303)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: str) -> HTMLResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    status = read_status(job)
    output_items = []
    for item in sorted((job / "output").glob("*")):
        if item.is_file():
            safe_name = html.escape(item.name)
            download_href = html.escape(
                f"/jobs/{quote(job_id, safe='')}/output/{quote(item.name, safe='')}"
            )
            size = item.stat().st_size
            output_items.append(
                f'<li><a href="{download_href}">{safe_name}</a> '
                f'<span class="muted">({size} bytes)</span></li>'
            )
    if not output_items:
        output_items.append('<li class="muted">No outputs yet.</li>')

    log_items = []
    for item in sorted((job / "logs").glob("*")):
        if item.is_file():
            log_items.append(f"<li>{html.escape(item.name)}</li>")
    if not log_items:
        log_items.append('<li class="muted">No logs yet.</li>')

    return page("Job", f"""
      <p><a href="/">&larr; Back to dashboard</a></p>
      <div class="card">
        <h1>Job {html.escape(job_id)}</h1>
        <p>{status_badge(status.get('status', 'unknown'))} {state_badge(status.get('state', 'production'))}</p>
        <p><strong>Step:</strong> {html.escape(status.get('step', 'unknown'))}</p>
        <p><strong>Message:</strong> {html.escape(status.get('message', ''))}</p>
        <p><strong>Updated:</strong> {html.escape(status.get('updated_at', ''))}</p>
      </div>
      {job_state_controls(job_id, status.get('state', 'production'))}
      <div class="card"><h2>Outputs</h2><ul>{''.join(output_items)}</ul></div>
      <div class="card"><h2>Logs</h2><ul>{''.join(log_items)}</ul></div>
    """)


@router.post("/jobs/{job_id}/state")
def update_job_state(job_id: str, state: str = Form(...)) -> RedirectResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    requested_state = state.strip().lower()
    if requested_state not in JOB_STATES:
        raise HTTPException(status_code=400, detail="Invalid job state")

    set_job_state(job, requested_state)
    return RedirectResponse(url=f"/jobs/{quote(job_id, safe='')}", status_code=303)


@router.get("/jobs/{job_id}/output/{filename}")
def download_output(job_id: str, filename: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if filename in {"", ".", ".."} or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    output_dir = (job / "output").resolve()
    file_path = (output_dir / filename).resolve()

    try:
        file_path.relative_to(output_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )
