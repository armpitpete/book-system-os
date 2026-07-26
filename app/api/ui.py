from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.services.job_queue import (
    JOB_STATES,
    cleanup_old_test_jobs,
    create_job,
    get_job,
    list_jobs,
    read_job_events,
    read_status,
    retry_job,
    set_job_state,
)
from app.services.security import current_csrf_token
from app.version import APP_VERSION, git_commit_label

router = APIRouter(dependencies=[Depends(dashboard_auth)])

DASHBOARD_JOB_STATES = {"test", "production"}

PAGE_STYLE = """
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; background: #20262c; color: #f4f1e8; }
    main { max-width: 980px; margin: 0 auto; padding: 24px; }
    h1, h2, h3 { line-height: 1.15; color: #ffffff; }
    .card { background: #2b3137; border: 1px solid #3b424a; border-radius: 14px; padding: 18px; margin: 16px 0; box-shadow: 0 1px 6px rgba(0,0,0,.22); }
    textarea, input, select { width: 100%; box-sizing: border-box; padding: 12px; border: 1px solid #4a535c; border-radius: 10px; font: inherit; background: #1f252b; color: #f4f1e8; }
    textarea { min-height: 320px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
    button, .button { display: inline-block; background: #3b424a; color: #f4f1e8; border: 1px solid #59636d; border-radius: 10px; padding: 10px 14px; text-decoration: none; font-weight: 650; cursor: pointer; }
    .danger { background: #7f1d1d; color: #fee2e2; border-color: #b91c1c; }
    .secondary { background: #2b3137; color: #f4f1e8; border: 1px solid #59636d; }
    .muted { color: #c6cbd2; }
    .status { display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 0.9rem; background: #3b424a; color: #f4f1e8; }
    .queued { background: #7a5d12; color: #fff7d6; }
    .running { background: #1e4f7a; color: #dbeafe; }
    .done { background: #166534; color: #dcfce7; }
    .failed { background: #7f1d1d; color: #fee2e2; }
    .state { display: inline-block; padding: 4px 9px; border-radius: 999px; font-size: 0.9rem; background: #3b424a; color: #f4f1e8; }
    .state.production { background: #374151; color: #e9edf5; }
    .state.test { background: #6b4f12; color: #fff7d6; }
    .state.archived { background: #4b5563; color: #e5e7eb; }
    code { background: #3b424a; color: #f4f1e8; padding: 2px 5px; border-radius: 5px; }
    pre.log-snippet { max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-word; background: #171c21; color: #f4f1e8; border: 1px solid #3b424a; border-radius: 10px; padding: 12px; font-size: 0.92rem; }
    details.log-viewer { margin: 12px 0; }
    details.log-viewer summary { cursor: pointer; font-weight: 650; }
    ::placeholder { color: #aeb5bc; }
    option { background: #1f252b; color: #f4f1e8; }
    a { color: #f4f1e8; }
    .version-label { margin-top: 28px; padding-top: 14px; border-top: 1px solid #3b424a; color: #aeb5bc; font-size: 0.9rem; }
"""


def version_label() -> str:
    return f"Book System OS v{APP_VERSION} - commit {git_commit_label()}"


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{PAGE_STYLE}</style>
</head>
<body>
  <main>
    {body}
    <footer class="version-label">{html.escape(version_label())}</footer>
  </main>
</body>
</html>"""
    )


def csrf_field() -> str:
    token = current_csrf_token()
    if not token:
        return ""
    return (
        '<input type="hidden" name="csrf_token" '
        f'value="{html.escape(token, quote=True)}">'
    )


def post_form(action: str, body: str, *, style: str = "") -> str:
    style_attr = (
        f' style="{html.escape(style, quote=True)}"'
        if style
        else ""
    )
    return (
        f'<form method="post" action="{html.escape(action, quote=True)}"{style_attr}>'
        f"{csrf_field()}{body}</form>"
    )


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
        controls.append(
            post_form(
                f"/jobs/{safe_job_id}/state",
                (
                    f'<button class="{button_class}" type="submit" '
                    f'name="state" value="{target_state}">{label}</button>'
                ),
                style="display: inline-block; margin: 0 8px 8px 0;",
            )
        )

    return f"""
      <div class="card">
        <h2>Lifecycle</h2>
        <p class="muted">Current lifecycle state: {state_badge(current_state)}</p>
        {''.join(controls)}
      </div>
    """


def retry_controls(job_id: str, status: str) -> str:
    if status != "failed":
        return ""

    safe_job_id = quote(job_id, safe="")
    form = post_form(
        f"/jobs/{safe_job_id}/retry",
        '<button type="submit">Retry failed job</button>',
    )
    return f"""
      <div class="card">
        <h2>Retry</h2>
        <p class="muted">Retry this failed job using the same input Markdown.</p>
        {form}
      </div>
    """


def compact_message(message: str, *, limit: int = 120) -> str:
    clean = " ".join((message or "").split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1].rstrip()}…"


def dashboard_status_summary(status: dict) -> str:
    step = html.escape(status.get("step", "unknown"))
    message = compact_message(status.get("message", ""))
    if not message:
        return f"Step: {step}"
    return f"Step: {step} &mdash; {html.escape(message)}"


def read_log_snippet(path: Path, *, limit: int = 12000) -> tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Could not read log: {exc}", False

    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def log_viewer_item(path: Path) -> str:
    snippet, truncated = read_log_snippet(path)
    safe_name = html.escape(path.name)
    safe_snippet = html.escape(snippet)
    size = path.stat().st_size
    truncated_note = (
        '<p class="muted">Showing last 12,000 characters.</p>'
        if truncated
        else ""
    )
    return f"""
      <details class="log-viewer">
        <summary>{safe_name} <span class="muted">({size} bytes)</span></summary>
        {truncated_note}
        <pre class="log-snippet">{safe_snippet}</pre>
      </details>
    """


def retry_count_value(status: dict) -> int:
    try:
        count = int(status.get("retry_count", 0))
    except (TypeError, ValueError):
        return 0
    return count if count >= 0 else 0


def retry_metadata(status: dict) -> str:
    retry_count = retry_count_value(status)
    last_retry = status.get("last_retry_at") or "Never"
    return f"""
        <p><strong>Retry count:</strong> {retry_count}</p>
        <p><strong>Last retry:</strong> {html.escape(str(last_retry))}</p>
    """


def job_history_items(events: list[dict]) -> str:
    if not events:
        return '<p class="muted">No history yet.</p>'

    items = []
    for event in reversed(events):
        event_name = html.escape(str(event.get("event", "event")))
        created_at = html.escape(str(event.get("created_at", "")))
        message = html.escape(str(event.get("message", "")))
        retry_count = event.get("retry_count")
        retry_note = ""
        if retry_count is not None:
            retry_note = (
                f' <span class="muted">(retry #{html.escape(str(retry_count))})</span>'
            )
        message_line = f"<br>{message}" if message else ""
        items.append(
            f"<li><strong>{event_name}</strong>{retry_note}"
            f'<br><span class="muted">{created_at}</span>{message_line}</li>'
        )
    return f"<ul>{''.join(items)}</ul>"


def truthy_query(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "show"}


def selected_attr(current: bool, option: bool) -> str:
    return " selected" if current is option else ""


def cleanup_job_rows(jobs: list[dict]) -> str:
    if not jobs:
        return '<p class="muted">No eligible old test jobs found.</p>'

    items = []
    for job in jobs:
        job_id = html.escape(str(job.get("job_id", "unknown")))
        status = html.escape(str(job.get("status", "unknown")))
        created_at = html.escape(str(job.get("created_at", "unknown")))
        age_days = html.escape(str(job.get("age_days", "unknown")))
        items.append(
            f"<li><strong>{job_id}</strong>"
            f'<br><span class="muted">status: {status}; created: {created_at}; '
            f"age: {age_days} days</span></li>"
        )
    return f"<ul>{''.join(items)}</ul>"


def cleanup_result_page(result: dict) -> HTMLResponse:
    dry_run = bool(result.get("dry_run"))
    days = html.escape(str(result.get("older_than_days", 7)))
    eligible_count = int(result.get("eligible_count", 0))
    archived_count = int(result.get("archived_count", 0))
    rows = cleanup_job_rows(result.get("jobs", []))

    if dry_run and eligible_count:
        action = post_form(
            "/jobs/cleanup-test-jobs",
            (
                f'<input type="hidden" name="older_than_days" value="{days}">'
                '<button class="danger" type="submit" name="confirm" value="archive">'
                "Archive eligible test jobs</button>"
                '<a class="button secondary" href="/">Cancel</a>'
            ),
        )
        summary = f"{eligible_count} old test job(s) are eligible for archive."
    elif dry_run:
        action = '<p><a class="button" href="/">Back to dashboard</a></p>'
        summary = "No old test jobs are eligible for archive."
    else:
        action = '<p><a class="button" href="/">Back to dashboard</a></p>'
        summary = f"Archived {archived_count} old test job(s)."

    return page(
        "Cleanup old test jobs",
        f"""
      <p><a href="/">&larr; Back to dashboard</a></p>
      <div class="card">
        <h1>Cleanup old test jobs</h1>
        <p class="muted">Threshold: {days} day(s).</p>
        <p>{html.escape(summary)}</p>
        {rows}
        {action}
      </div>
    """,
    )


def dashboard_job_cards(
    *,
    show_test: bool,
    show_failed: bool,
    show_archived: bool,
) -> str:
    cards = []
    for job in list_jobs():
        status = read_status(job)
        job_state = status.get("state", "production")
        job_status = status.get("status", "unknown")

        if job_state == "test" and not show_test:
            continue
        if job_state == "archived" and not show_archived:
            continue
        if job_status == "failed" and not show_failed:
            continue

        job_id = job.name
        safe_job_id = html.escape(job_id)
        job_href = html.escape(f"/jobs/{quote(job_id, safe='')}", quote=True)
        meta_title = "Untitled"
        meta = job / "metadata.json"
        if meta.exists():
            try:
                meta_title = json.loads(
                    meta.read_text(encoding="utf-8")
                ).get("title", "Untitled")
            except Exception:
                pass

        cards.append(
            f"""
        <div class="card">
          <h3>{html.escape(meta_title)}</h3>
          <p>{status_badge(job_status)} {state_badge(job_state)}
             <span class="muted">{safe_job_id}</span></p>
          <p class="muted">{dashboard_status_summary(status)}</p>
          <p><a class="button" href="{job_href}">Open job</a></p>
        </div>
        """
        )
        if len(cards) >= 30:
            break

    return (
        "\n".join(cards)
        if cards
        else '<p class="muted">No jobs match the current filters.</p>'
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(
    show_test: str = Query("1"),
    show_failed: str = Query("1"),
    show_archived: str = Query("0"),
) -> HTMLResponse:
    show_test_bool = truthy_query(show_test, default=True)
    show_failed_bool = truthy_query(show_failed, default=True)
    show_archived_bool = truthy_query(show_archived, default=False)

    submit = post_form(
        "/submit-form",
        """
          <p><label>Title<br>
            <input name="title" value="A Book for Neurodivergent Minds">
          </label></p>
          <p><label>Job type<br>
            <select name="state">
              <option value="test" selected>Test — default for manual checks</option>
              <option value="production">Production — retained as a real publication job</option>
            </select>
          </label></p>
          <p><label>Markdown<br>
            <textarea name="content" required placeholder="# Title&#10;&#10;Paste Markdown here..."></textarea>
          </label></p>
          <button type="submit">Queue book build</button>
        """,
    )

    cleanup = post_form(
        "/jobs/cleanup-test-jobs",
        """
          <p><label>Archive test jobs older than this many days<br>
            <input name="older_than_days" type="number" min="1" max="365" value="7">
          </label></p>
          <button type="submit">Preview cleanup</button>
        """,
    )

    job_list = dashboard_job_cards(
        show_test=show_test_bool,
        show_failed=show_failed_bool,
        show_archived=show_archived_bool,
    )

    return page(
        "Publishing Dashboard",
        f"""
      <h1>Publishing Dashboard</h1>
      <p class="muted">Domain target: <code>publish.toiletrage.co.uk</code></p>

      <div class="card">
        <h2>Queue book build</h2>
        {submit}
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

      <div class="card">
        <h2>Cleanup old test jobs</h2>
        <p class="muted">Preview old test jobs before archiving them.
        Running and queued jobs are never touched.</p>
        {cleanup}
      </div>

      <h2>Jobs</h2>
      <p class="muted">Showing up to 30 jobs matching the current filters.</p>
      {job_list}
    """,
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
    if not content.strip():
        raise HTTPException(status_code=400, detail="Markdown content is required")

    create_job(title=title, markdown=content, state=requested_state)
    return RedirectResponse(url="/", status_code=303)


@router.post("/jobs/cleanup-test-jobs", response_class=HTMLResponse)
def cleanup_test_jobs(
    older_than_days: int = Form(7),
    confirm: str = Form(""),
) -> HTMLResponse:
    days = max(1, min(365, int(older_than_days)))
    dry_run = confirm.strip().lower() != "archive"
    result = cleanup_old_test_jobs(older_than_days=days, dry_run=dry_run)
    return cleanup_result_page(result)


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
                f"/jobs/{quote(job_id, safe='')}/output/{quote(item.name, safe='')}",
                quote=True,
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
            log_items.append(log_viewer_item(item))
    if not log_items:
        log_items.append('<p class="muted">No logs yet.</p>')

    history_items = job_history_items(read_job_events(job))

    return page(
        "Job",
        f"""
      <p><a href="/">&larr; Back to dashboard</a></p>
      <div class="card">
        <h1>Job {html.escape(job_id)}</h1>
        <p>{status_badge(status.get('status', 'unknown'))}
           {state_badge(status.get('state', 'production'))}</p>
        <p><strong>Step:</strong> {html.escape(status.get('step', 'unknown'))}</p>
        <p><strong>Message:</strong> {html.escape(status.get('message', ''))}</p>
        <p><strong>Updated:</strong> {html.escape(status.get('updated_at', ''))}</p>
        {retry_metadata(status)}
      </div>
      {job_state_controls(job_id, status.get('state', 'production'))}
      {retry_controls(job_id, status.get('status', 'unknown'))}
      <div class="card"><h2>History</h2>{history_items}</div>
      <div class="card"><h2>Outputs</h2><ul>{''.join(output_items)}</ul></div>
      <div class="card"><h2>Logs</h2>{''.join(log_items)}</div>
    """,
    )


@router.post("/jobs/{job_id}/retry")
def retry_failed_job(job_id: str) -> RedirectResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        retry_job(job)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(
        url=f"/jobs/{quote(job_id, safe='')}",
        status_code=303,
    )


@router.post("/jobs/{job_id}/state")
def update_job_state(job_id: str, state: str = Form(...)) -> RedirectResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    requested_state = state.strip().lower()
    if requested_state not in JOB_STATES:
        raise HTTPException(status_code=400, detail="Invalid job state")

    set_job_state(job, requested_state)
    return RedirectResponse(
        url=f"/jobs/{quote(job_id, safe='')}",
        status_code=303,
    )


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid filename") from exc

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )
