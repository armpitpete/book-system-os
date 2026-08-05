from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.auth import dashboard_auth
from app.api.ui import page, post_form
from app.services.revision_studio import (
    RevisionStudioError,
    compare_proposal,
    create_document,
    create_proposal,
    decide_proposal,
    get_current,
    get_history,
    get_proposal,
    list_proposals,
    revision_root,
)

router = APIRouter(dependencies=[Depends(dashboard_auth)])


EXTRA_STYLE = """
<style>
  .revision-nav { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0; }
  .revision-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .revision-grid .card { margin: 0; }
  .revision-text { min-height: 260px; white-space: pre-wrap; overflow-wrap: anywhere; background: #171c21; border: 1px solid #3b424a; border-radius: 10px; padding: 14px; }
  .revision-diff { max-height: 520px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: #171c21; border: 1px solid #3b424a; border-radius: 10px; padding: 14px; }
  .revision-state { display: inline-block; padding: 4px 9px; border-radius: 999px; background: #3b424a; }
  .revision-state.accepted, .revision-state.partially_accepted { background: #166534; color: #dcfce7; }
  .revision-state.rejected { background: #7f1d1d; color: #fee2e2; }
  .revision-state.kept_for_later { background: #6b4f12; color: #fff7d6; }
  .revision-actions { display: grid; gap: 14px; }
  .revision-actions form { border-top: 1px solid #3b424a; padding-top: 14px; }
  .revision-actions button { min-height: 48px; }
  .revision-check { display: block; padding: 10px 0; }
  .revision-check input { width: auto; margin-right: 8px; }
  .revision-warning { border-left: 5px solid #d6a72d; padding-left: 12px; }
  @media (max-width: 700px) {
    main { padding: 16px; }
    textarea { min-height: 240px; }
  }
</style>
"""


def _safe(value: object) -> str:
    return html.escape(str(value))


def _href(value: str) -> str:
    return quote(value, safe="")


def _state_badge(state: str) -> str:
    safe = _safe(state)
    cls = state if state in {
        "proposed",
        "accepted",
        "partially_accepted",
        "kept_for_later",
        "rejected",
    } else ""
    return f'<span class="revision-state {cls}">{safe.replace("_", " ")}</span>'


def _lines(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _metadata_list(title: str, values: list[str]) -> str:
    if not values:
        return ""
    items = "".join(f"<li>{_safe(value)}</li>" for value in values)
    return f"<h3>{_safe(title)}</h3><ul>{items}</ul>"


def _error_page(title: str, exc: RevisionStudioError, back: str) -> HTMLResponse:
    response = page(
        title,
        EXTRA_STYLE
        + f"""
        <div class="revision-nav"><a class="button secondary" href="{html.escape(back, quote=True)}">Back</a></div>
        <div class="card revision-warning">
          <h1>{_safe(title)}</h1>
          <p><strong>{_safe(exc.code)}</strong></p>
          <p>{_safe(exc)}</p>
        </div>
        """,
    )
    response.status_code = exc.status_code
    return response


def _document_summaries(root: Path) -> list[dict]:
    summaries: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        try:
            current = get_current(child.name)
            proposals = list_proposals(child.name)
        except RevisionStudioError:
            continue
        summaries.append(
            {
                "document_id": child.name,
                "title": current["title"],
                "version_id": current["version_id"],
                "proposal_count": len(proposals),
                "open_count": sum(
                    1 for proposal in proposals if proposal.get("state") == "proposed"
                ),
            }
        )
    return summaries


@router.get("/revision-studio", include_in_schema=False)
def revision_studio_redirect() -> RedirectResponse:
    return RedirectResponse("/revisions", status_code=303)


@router.get("/revisions", response_class=HTMLResponse, include_in_schema=False)
def revision_index() -> HTMLResponse:
    summaries = _document_summaries(revision_root())
    cards = []
    for item in summaries:
        document_id = str(item["document_id"])
        cards.append(
            f"""
            <div class="card">
              <h2>{_safe(item['title'])}</h2>
              <p class="muted"><code>{_safe(document_id)}</code></p>
              <p>{item['open_count']} open proposal(s); {item['proposal_count']} retained total.</p>
              <p class="muted">Current: <code>{_safe(item['version_id'])}</code></p>
              <a class="button" href="/revisions/{_href(document_id)}">Open</a>
            </div>
            """
        )
    content = "".join(cards) or '<div class="card"><p class="muted">No revision documents yet.</p></div>'
    return page(
        "Revision Studio",
        EXTRA_STYLE
        + f"""
        <div class="revision-nav">
          <a class="button secondary" href="/">Dashboard</a>
          <a class="button" href="/revisions/new">New document</a>
        </div>
        <div class="card">
          <h1>Revision Studio</h1>
          <p>Keep Current safe. Create Proposed alternatives. Compare them before a human decision.</p>
        </div>
        <div class="revision-grid">{content}</div>
        """,
    )


@router.get("/revisions/new", response_class=HTMLResponse, include_in_schema=False)
def revision_new_document() -> HTMLResponse:
    form = post_form(
        "/revisions",
        """
        <label>Document ID<input name="document_id" required maxlength="128" placeholder="chapter-07"></label>
        <label>Title<input name="title" required maxlength="200"></label>
        <label>Current manuscript<textarea name="content" required></textarea></label>
        <label>Your name<input name="actor" required maxlength="200"></label>
        <label>Authority reference<input name="authority_ref" required maxlength="500" placeholder="owner:initial-acceptance"></label>
        <button type="submit">Create Current</button>
        """,
    )
    return page(
        "New revision document",
        EXTRA_STYLE
        + f"""
        <div class="revision-nav"><a class="button secondary" href="/revisions">Back</a></div>
        <div class="card"><h1>New revision document</h1>{form}</div>
        """,
    )


@router.post("/revisions", include_in_schema=False)
def revision_create_document(
    document_id: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    actor: str = Form(...),
    authority_ref: str = Form(...),
) -> HTMLResponse | RedirectResponse:
    try:
        created = create_document(
            document_id=document_id,
            title=title,
            content=content,
            actor=actor,
            authority_ref=authority_ref,
        )
    except RevisionStudioError as exc:
        return _error_page("Could not create Current", exc, "/revisions/new")
    return RedirectResponse(
        f"/revisions/{_href(str(created['document_id']))}", status_code=303
    )


@router.get("/revisions/{document_id}", response_class=HTMLResponse, include_in_schema=False)
def revision_document(document_id: str) -> HTMLResponse:
    try:
        current = get_current(document_id)
        proposals = list_proposals(document_id)
    except RevisionStudioError as exc:
        return _error_page("Could not open revision document", exc, "/revisions")

    proposal_cards = []
    for proposal in reversed(proposals):
        proposal_id = str(proposal["proposal_id"])
        proposal_cards.append(
            f"""
            <div class="card">
              <p>{_state_badge(str(proposal.get('state', 'unknown')))}</p>
              <h3>{_safe(proposal.get('rationale', 'Proposal'))}</h3>
              <p class="muted">By {_safe(proposal.get('created_by', 'unknown'))} · {_safe(proposal.get('created_by_kind', 'unknown'))}</p>
              <p>{len(proposal.get('changed_units', []))} changed unit(s).</p>
              <a class="button" href="/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}">Compare</a>
            </div>
            """
        )
    proposals_html = "".join(proposal_cards) or '<p class="muted">No proposals yet.</p>'

    create_form = post_form(
        f"/revisions/{_href(document_id)}/proposals",
        """
        <label>Proposed manuscript<textarea name="content" required></textarea></label>
        <label>Why this change?<textarea name="rationale" required style="min-height:120px"></textarea></label>
        <label>Created by<input name="created_by" required maxlength="200"></label>
        <label>Creator kind
          <select name="created_by_kind" required>
            <option value="human">Human</option>
            <option value="assistant">Assistant</option>
            <option value="automation">Automation</option>
            <option value="import">Import</option>
          </select>
        </label>
        <label>Evidence references, one per line<textarea name="evidence_refs" style="min-height:100px"></textarea></label>
        <label>Validation references, one per line<textarea name="validation_refs" style="min-height:100px"></textarea></label>
        <label>Consequences, one per line<textarea name="consequence_notes" style="min-height:100px"></textarea></label>
        <label>Risks, one per line<textarea name="risk_notes" style="min-height:100px"></textarea></label>
        <button type="submit">Create Proposed</button>
        """,
    )

    return page(
        str(current["title"]),
        EXTRA_STYLE
        + f"""
        <div class="revision-nav">
          <a class="button secondary" href="/revisions">All documents</a>
          <a class="button secondary" href="/revisions/{_href(document_id)}/history">History</a>
        </div>
        <div class="card">
          <p class="muted">Current · <code>{_safe(current['version_id'])}</code></p>
          <h1>{_safe(current['title'])}</h1>
          <div class="revision-text">{_safe(current['content'])}</div>
        </div>
        <div class="card"><h2>Create Proposed</h2>{create_form}</div>
        <h2>Proposals</h2>
        <div class="revision-grid">{proposals_html}</div>
        """,
    )


@router.post("/revisions/{document_id}/proposals", include_in_schema=False)
def revision_create_proposal(
    document_id: str,
    content: str = Form(...),
    rationale: str = Form(...),
    created_by: str = Form(...),
    created_by_kind: str = Form(...),
    evidence_refs: str = Form(""),
    validation_refs: str = Form(""),
    consequence_notes: str = Form(""),
    risk_notes: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    try:
        proposal = create_proposal(
            document_id=document_id,
            content=content,
            rationale=rationale,
            created_by=created_by,
            created_by_kind=created_by_kind,  # type: ignore[arg-type]
            evidence_refs=_lines(evidence_refs),
            validation_refs=_lines(validation_refs),
            consequence_notes=_lines(consequence_notes),
            risk_notes=_lines(risk_notes),
        )
    except RevisionStudioError as exc:
        return _error_page(
            "Could not create Proposed", exc, f"/revisions/{_href(document_id)}"
        )
    return RedirectResponse(
        f"/revisions/{_href(document_id)}/proposals/{_href(str(proposal['proposal_id']))}",
        status_code=303,
    )


def _decision_fields(action: str, label: str, css_class: str = "") -> str:
    return f"""
      <input type="hidden" name="action" value="{html.escape(action, quote=True)}">
      <label>Your name<input name="actor" required maxlength="200"></label>
      <label>Authority reference<input name="authority_ref" required maxlength="500"></label>
      <label>Decision note<textarea name="note" style="min-height:90px"></textarea></label>
      <button class="{html.escape(css_class, quote=True)}" type="submit">{_safe(label)}</button>
    """


@router.get(
    "/revisions/{document_id}/proposals/{proposal_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def revision_compare(document_id: str, proposal_id: str) -> HTMLResponse:
    try:
        current = get_current(document_id)
        proposal = get_proposal(document_id, proposal_id)
        comparison = compare_proposal(document_id, proposal_id)
        stale_note = ""
    except RevisionStudioError as exc:
        if exc.code != "stale-proposal":
            return _error_page(
                "Could not compare proposal", exc, f"/revisions/{_href(document_id)}"
            )
        current = get_current(document_id)
        proposal = get_proposal(document_id, proposal_id)
        comparison = None
        stale_note = (
            '<div class="card revision-warning"><h2>Stale proposal</h2>'
            '<p>Current has moved since this proposal was created. It remains in History but cannot be accepted against the new Current.</p></div>'
        )

    evidence = _metadata_list("Evidence", list(proposal.get("evidence_refs", [])))
    validation = _metadata_list("Validation", list(proposal.get("validation_refs", [])))
    consequences = _metadata_list("Consequences", list(proposal.get("consequence_notes", [])))
    risks = _metadata_list("Risks", list(proposal.get("risk_notes", [])))
    diff = _safe(comparison["unified_diff"]) if comparison else "Comparison unavailable because the proposal is stale."

    actions = ""
    if proposal.get("state") == "proposed" and comparison is not None:
        accept_all = post_form(
            f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}/decision",
            _decision_fields("accept_all", "Accept all"),
        )
        keep = post_form(
            f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}/decision",
            _decision_fields("keep_for_later", "Keep for later", "secondary"),
        )
        reject = post_form(
            f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}/decision",
            _decision_fields("reject", "Reject", "danger"),
        )
        checkboxes = "".join(
            f'<label class="revision-check"><input type="checkbox" name="accepted_units" value="{html.escape(unit, quote=True)}">{_safe(unit)}</label>'
            for unit in comparison["changed_units"]
        )
        partial = post_form(
            f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}/decision",
            f"""
              <input type="hidden" name="action" value="accept_part">
              <p>Select the changed units to accept, then supply the actual merged manuscript.</p>
              {checkboxes}
              <label>Merged manuscript<textarea name="merged_content" required>{_safe(current['content'])}</textarea></label>
              <label>Your name<input name="actor" required maxlength="200"></label>
              <label>Authority reference<input name="authority_ref" required maxlength="500"></label>
              <label>Decision note<textarea name="note" style="min-height:90px"></textarea></label>
              <button type="submit">Accept selected parts</button>
            """,
        )
        actions = f"<div class="card revision-actions"><h2>Decision</h2>{accept_all}{partial}{keep}{reject}</div>"
    elif proposal.get("decision"):
        decision = proposal["decision"]
        actions = f"""
        <div class="card">
          <h2>Decision recorded</h2>
          <p><strong>{_safe(decision.get('action'))}</strong> by {_safe(decision.get('actor'))}</p>
          <p class="muted">Authority: {_safe(decision.get('authority_ref'))}</p>
        </div>
        """

    return page(
        "Compare revision",
        EXTRA_STYLE
        + f"""
        <div class="revision-nav">
          <a class="button secondary" href="/revisions/{_href(document_id)}">Document</a>
          <a class="button secondary" href="/revisions/{_href(document_id)}/history">History</a>
        </div>
        {stale_note}
        <div class="card">
          <p>{_state_badge(str(proposal.get('state', 'unknown')))}</p>
          <h1>Compare</h1>
          <p>{_safe(proposal.get('rationale', ''))}</p>
          <p class="muted">Created by {_safe(proposal.get('created_by'))} · {_safe(proposal.get('created_by_kind'))}</p>
          {evidence}{validation}{consequences}{risks}
        </div>
        <div class="revision-grid">
          <div class="card"><h2>Current</h2><div class="revision-text">{_safe(current['content'])}</div></div>
          <div class="card"><h2>Proposed</h2><div class="revision-text">{_safe(proposal['content'])}</div></div>
        </div>
        <div class="card"><h2>Difference</h2><pre class="revision-diff">{diff}</pre></div>
        {actions}
        """,
    )


@router.post(
    "/revisions/{document_id}/proposals/{proposal_id}/decision",
    include_in_schema=False,
)
def revision_decision(
    document_id: str,
    proposal_id: str,
    action: str = Form(...),
    actor: str = Form(...),
    authority_ref: str = Form(...),
    accepted_units: list[str] = Form(default=[]),
    merged_content: str | None = Form(default=None),
    note: str | None = Form(default=None),
) -> HTMLResponse | RedirectResponse:
    try:
        decide_proposal(
            document_id=document_id,
            proposal_id=proposal_id,
            action=action,  # type: ignore[arg-type]
            actor=actor,
            authority_ref=authority_ref,
            accepted_units=accepted_units,
            merged_content=merged_content,
            note=note,
        )
    except RevisionStudioError as exc:
        return _error_page(
            "Could not record decision",
            exc,
            f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}",
        )
    return RedirectResponse(
        f"/revisions/{_href(document_id)}/proposals/{_href(proposal_id)}",
        status_code=303,
    )


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

    items = []
    for event in reversed(history):
        details = "".join(
            f"<li><strong>{_safe(key.replace('_', ' '))}:</strong> {_safe(value)}</li>"
            for key, value in event.items()
            if key not in {"event", "created_at"} and value not in {None, [], ""}
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
    content = "".join(items) or '<div class="card"><p class="muted">No history yet.</p></div>'
    return page(
        "Revision history",
        EXTRA_STYLE
        + f"""
        <div class="revision-nav">
          <a class="button secondary" href="/revisions/{_href(document_id)}">Document</a>
          <a class="button secondary" href="/revisions">All documents</a>
        </div>
        <div class="card"><h1>History · {_safe(current['title'])}</h1></div>
        {content}
        """,
    )
