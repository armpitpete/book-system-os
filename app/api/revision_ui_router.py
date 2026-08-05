from __future__ import annotations

from fastapi.responses import HTMLResponse, Response

from app.api.revision_ui import EXTRA_STYLE, _error_page, _href, _safe, router
from app.api.ui import page
from app.services.revision_package import build_revision_package
from app.services.revision_studio import RevisionStudioError, get_current, get_history

# Keep the visual surface assembled in one exported router while replacing the
# first-pass History endpoint with the normalised renderer below.
router.routes[:] = [
    route for route in router.routes if getattr(route, "name", "") != "revision_history"
]


def _display_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


@router.get(
    "/revisions/{document_id}/history",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def revision_history(document_id: str) -> HTMLResponse:
    try:
        current = get_current(document_id)
        history = get_history(document_id)
    except RevisionStudioError as exc:
        return _error_page("Could not open History", exc, "/revisions")

    items: list[str] = []
    for event in reversed(history):
        details = "".join(
            f"<li><strong>{_safe(key.replace('_', ' '))}:</strong> "
            f"{_safe(_display_value(value))}</li>"
            for key, value in event.items()
            if key not in {"event", "created_at"}
            and value is not None
            and value != []
            and value != ""
        )
        items.append(
            f"""
            <div class="card">
              <h2>{_safe(str(event.get('event', 'event')).replace('_', ' '))}</h2>
              <p class="muted">{_safe(event.get('created_at', ''))}</p>
              <ul>{details}</ul>
            </div>
            """
        )

    content = "".join(items) or (
        '<div class="card"><p class="muted">No history yet.</p></div>'
    )
    return page(
        "Revision history",
        EXTRA_STYLE
        + f"""
        <div class="revision-nav">
          <a class="button secondary" href="/revisions/{_href(document_id)}">Document</a>
          <a class="button secondary" href="/revisions">All documents</a>
          <a class="button" href="/revisions/{_href(document_id)}/package">Download portable package</a>
        </div>
        <div class="card">
          <h1>History · {_safe(current['title'])}</h1>
          <p>The portable package contains Current, every retained proposal, decisions, History and a verification manifest.</p>
        </div>
        {content}
        """,
    )


@router.get(
    "/revisions/{document_id}/package",
    include_in_schema=False,
    response_model=None,
)
def revision_package_download(document_id: str) -> Response:
    try:
        package = build_revision_package(document_id)
    except RevisionStudioError as exc:
        return _error_page(
            "Could not build portable package",
            exc,
            f"/revisions/{_href(document_id)}/history",
        )
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "X-Content-SHA256": package.sha256,
            "X-Revision-Package-Version": "0.1",
        },
    )
