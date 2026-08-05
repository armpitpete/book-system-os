from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services.revision_studio import (
    create_document,
    create_proposal,
    get_current,
    get_proposal,
    list_proposals,
)


CURRENT = "# Chapter\n\nThe path crossed the field.\n\nIt ended at the river.\n"
PROPOSED = "# Chapter\n\nThe old path crossed the field.\n\nIt ended beside the river.\n"
PARTIAL = "# Chapter\n\nThe old path crossed the field.\n\nIt ended at the river.\n"


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("BOOK_SYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "local")
    monkeypatch.delenv("BOOK_API_KEY", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BOOK_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("BOOK_SECURITY_CSRF_ENABLED", raising=False)
    return TestClient(app)


def create_current_through_ui(client: TestClient, document_id: str = "chapter-07") -> None:
    response = client.post(
        "/revisions",
        data={
            "document_id": document_id,
            "title": "Chapter Seven",
            "content": CURRENT,
            "actor": "Merrin",
            "authority_ref": "test:initial",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/revisions/{document_id}"


def create_proposal_through_ui(client: TestClient, document_id: str = "chapter-07") -> str:
    response = client.post(
        f"/revisions/{document_id}/proposals",
        data={
            "content": PROPOSED,
            "rationale": "Clarify the route without changing the event.",
            "created_by": "clarity-assistant",
            "created_by_kind": "assistant",
            "evidence_refs": "reader:3\nsource:map",
            "validation_refs": "check:clarity",
            "consequence_notes": "Two sentences change.",
            "risk_notes": "The cadence may become less spare.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    marker = f"/revisions/{document_id}/proposals/"
    assert response.headers["location"].startswith(marker)
    return response.headers["location"].removeprefix(marker)


def test_revision_studio_index_is_clear_and_touch_friendly(client: TestClient) -> None:
    response = client.get("/revisions")
    assert response.status_code == 200
    assert "Revision Studio" in response.text
    assert "Keep Current safe" in response.text
    assert "New document" in response.text
    assert "min-height: 48px" in response.text
    assert client.get("/revision-studio", follow_redirects=False).status_code == 303


def test_production_revision_studio_uses_dashboard_auth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOK_SYSTEM_ENV", "production")
    monkeypatch.setenv("BOOK_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("BOOK_ADMIN_PASSWORD", "correct-password")

    assert client.get("/revisions").status_code == 401
    wrong = client.get(
        "/revisions", headers=basic_auth("operator", "wrong-password")
    )
    assert wrong.status_code == 401
    accepted = client.get(
        "/revisions", headers=basic_auth("operator", "correct-password")
    )
    assert accepted.status_code == 200


def test_browser_flow_creates_current_and_escapes_manuscript_html(
    client: TestClient,
) -> None:
    response = client.post(
        "/revisions",
        data={
            "document_id": "escaped",
            "title": "Escaped <Title>",
            "content": "# Safe\n\n<script>alert('x')</script>\n",
            "actor": "Merrin",
            "authority_ref": "test:escaped",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    document = client.get("/revisions/escaped")
    assert document.status_code == 200
    assert "Escaped &lt;Title&gt;" in document.text
    assert "&lt;script&gt;alert" in document.text
    assert "<script>alert('x')</script>" not in document.text
    assert "Current" in document.text
    assert "Create Proposed" in document.text
    assert get_current("escaped")["accepted_by"] == "Merrin"


def test_compare_page_shows_source_evidence_risk_diff_and_all_decisions(
    client: TestClient,
) -> None:
    create_current_through_ui(client)
    proposal_id = create_proposal_through_ui(client)

    comparison = client.get(f"/revisions/chapter-07/proposals/{proposal_id}")
    assert comparison.status_code == 200
    for text in (
        "Current",
        "Proposed",
        "Difference",
        "Evidence",
        "reader:3",
        "Validation",
        "check:clarity",
        "Consequences",
        "Risks",
        "Accept all",
        "Accept selected parts",
        "Keep for later",
        "Reject",
        "Your name",
        "Authority reference",
    ):
        assert text in comparison.text
    assert "-The path crossed the field." in comparison.text
    assert "+The old path crossed the field." in comparison.text


def test_keep_for_later_records_decision_and_history_without_changing_current(
    client: TestClient,
) -> None:
    create_current_through_ui(client)
    proposal_id = create_proposal_through_ui(client)
    before = get_current("chapter-07")

    decision = client.post(
        f"/revisions/chapter-07/proposals/{proposal_id}/decision",
        data={
            "action": "keep_for_later",
            "actor": "Merrin",
            "authority_ref": "test:keep",
            "note": "Useful alternative, not for this edition.",
        },
        follow_redirects=False,
    )
    assert decision.status_code == 303, decision.text

    after = get_current("chapter-07")
    retained = get_proposal("chapter-07", proposal_id)
    assert after["version_id"] == before["version_id"]
    assert retained["state"] == "kept_for_later"
    assert retained["content"] == PROPOSED

    decided_page = client.get(f"/revisions/chapter-07/proposals/{proposal_id}")
    assert decided_page.status_code == 200
    assert "Decision recorded" in decided_page.text
    assert "keep_for_later" in decided_page.text
    assert "Accept all" not in decided_page.text

    history = client.get("/revisions/chapter-07/history")
    assert history.status_code == 200
    assert "History · Chapter Seven" in history.text
    assert "current created" in history.text
    assert "proposal created" in history.text
    assert "proposal decided" in history.text
    assert "kept_for_later" in history.text


def test_accept_all_promotes_proposed_to_current(client: TestClient) -> None:
    create_current_through_ui(client)
    proposal_id = create_proposal_through_ui(client)

    decision = client.post(
        f"/revisions/chapter-07/proposals/{proposal_id}/decision",
        data={
            "action": "accept_all",
            "actor": "Merrin",
            "authority_ref": "test:accept-all",
        },
        follow_redirects=False,
    )
    assert decision.status_code == 303, decision.text
    assert get_current("chapter-07")["content"] == PROPOSED
    assert get_proposal("chapter-07", proposal_id)["state"] == "accepted"


def test_partial_acceptance_requires_and_records_actual_merged_manuscript(
    client: TestClient,
) -> None:
    create_current_through_ui(client)
    proposal_id = create_proposal_through_ui(client)
    proposal = get_proposal("chapter-07", proposal_id)
    assert len(proposal["changed_units"]) >= 2

    decision = client.post(
        f"/revisions/chapter-07/proposals/{proposal_id}/decision",
        data={
            "action": "accept_part",
            "actor": "Merrin",
            "authority_ref": "test:accept-part",
            "accepted_units": [proposal["changed_units"][0]],
            "merged_content": PARTIAL,
        },
        follow_redirects=False,
    )
    assert decision.status_code == 303, decision.text
    assert get_current("chapter-07")["content"] == PARTIAL
    decided = get_proposal("chapter-07", proposal_id)
    assert decided["state"] == "partially_accepted"
    assert decided["decision"]["accepted_units"] == [proposal["changed_units"][0]]


def test_reject_preserves_proposed_content_and_current(client: TestClient) -> None:
    create_current_through_ui(client)
    proposal_id = create_proposal_through_ui(client)
    before = get_current("chapter-07")

    decision = client.post(
        f"/revisions/chapter-07/proposals/{proposal_id}/decision",
        data={
            "action": "reject",
            "actor": "Merrin",
            "authority_ref": "test:reject",
        },
        follow_redirects=False,
    )
    assert decision.status_code == 303
    assert get_current("chapter-07")["version_id"] == before["version_id"]
    retained = get_proposal("chapter-07", proposal_id)
    assert retained["state"] == "rejected"
    assert retained["content"] == PROPOSED


def test_stale_proposal_is_visible_but_cannot_be_accepted(client: TestClient) -> None:
    create_document(
        document_id="stale",
        title="Stale test",
        content=CURRENT,
        actor="Merrin",
        authority_ref="test:initial",
    )
    first = create_proposal(
        document_id="stale",
        content=PROPOSED,
        rationale="First proposal.",
        created_by="assistant",
        created_by_kind="assistant",
    )
    second = create_proposal(
        document_id="stale",
        content=CURRENT.replace("field", "meadow"),
        rationale="Second proposal.",
        created_by="assistant",
        created_by_kind="assistant",
    )

    accepted = client.post(
        f"/revisions/stale/proposals/{first['proposal_id']}/decision",
        data={
            "action": "accept_all",
            "actor": "Merrin",
            "authority_ref": "test:first-wins",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303

    stale = client.get(f"/revisions/stale/proposals/{second['proposal_id']}")
    assert stale.status_code == 200
    assert "Stale proposal" in stale.text
    assert "cannot be accepted" in stale.text
    assert "Accept all" not in stale.text
    assert len(list_proposals("stale")) == 2


def test_status_reports_visual_revision_studio_as_implemented(client: TestClient) -> None:
    status = client.get("/api/v1/status")
    assert status.status_code == 200
    payload = status.json()
    assert "GET /revisions" in payload["implemented"]
    assert "Revision Studio visual interface" not in payload["not_yet_implemented"]
