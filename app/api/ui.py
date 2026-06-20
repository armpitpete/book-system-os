from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.services.job_queue import create_job, get_job, list_jobs, read_status

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
    textarea, input {{ width: 100%; box-sizing: border-box; padding: 12px; border: 1px solid #bbb6a7; border-radius: 10px; font: inherit; }}
    textarea {{ min-height: 320px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    button, .button {{ display: inline-block; background: #20262c; color: white; border: 0; border-radius: 10px; padding: 10px 14px; text-decoration: none; font-weight: 650; cursor: pointer; }}
    .muted {{ color: #60656c; }}
    .status {{ display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 0.9rem; background: #eee; }}
    .queued {{ background: #fff2c2; }} .running {{ background: #dbeafe; }} .done {{ background: #dcfce7; }} .failed {{ background: #fee2e2; }}
    code {{ background: #efeee8; padding: 2px 5px; border-radius: 5px; }}
  </style>
</head>
<body><main>{body}</main></body>
</html>""")


def status_badge(status: str) -> str:
    safe = html.escape(status or "unknown")
    cls = safe if safe in {"queued", "running", "done", "failed"} else ""
    return f'<span class="status {cls}">{safe}</span>'


@router.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    cards = []
    for job in list_jobs()[:30]:
        status = read_status(job)
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
          <p>{status_badge(status.get('status', 'unknown'))} <span class="muted">{job_id}</span></p>
          <p class="muted">Step: {html.escape(status.get('step', 'unknown'))} — {html.escape(status.get('message', ''))}</p>
          <p><a class="button" href="/jobs/{job_id}">Open job</a></p>
        </div>
        """)

    job_list = "\n".join(cards) if cards else '<p class="muted">No jobs yet.</p>'
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
      <h2>Jobs</h2>
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
      <p><a href="/">← Back to dashboard</a></p>
      <div class="card">
        <h1>Job {html.escape(job_id)}</h1>
        <p>{status_badge(status.get('status', 'unknown'))}</p>
        <p><strong>Step:</strong> {html.escape(status.get('step', 'unknown'))}</p>
        <p><strong>Message:</strong> {html.escape(status.get('message', ''))}</p>
        <p><strong>Updated:</strong> {html.escape(status.get('updated_at', ''))}</p>
      </div>
      <div class="card"><h2>Outputs</h2><ul>{''.join(output_items)}</ul></div>
      <div class="card"><h2>Logs</h2><ul>{''.join(log_items)}</ul></div>
    """)


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
