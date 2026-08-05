from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.revision_studio import (
    RevisionStudioError,
    compare_proposal,
    content_digest,
    create_document,
    create_proposal,
    decide_proposal,
    get_current,
    get_history,
    get_proposal,
    list_proposals,
)


CURRENT = "# Chapter\n\nThe path crossed the field.\n\nIt ended at the river.\n"
PROPOSED = "# Chapter\n\nThe old path crossed the field.\n\nIt ended beside the river.\n"
PARTIAL = "# Chapter\n\nThe old path crossed the field.\n\nIt ended at the river.\n"


def make_document(root: Path, document_id: str = "chapter-07") -> dict:
    return create_document(
        document_id=document_id,
        title="Chapter Seven",
        content=CURRENT,
        actor="Merrin",
        authority_ref="test:initial-acceptance",
        root=root,
    )


def make_proposal(root: Path, document_id: str = "chapter-07") -> dict:
    return create_proposal(
        document_id=document_id,
        content=PROPOSED,
        rationale="Clarify the route while preserving the event.",
        created_by="clarity-assistant",
        created_by_kind="assistant",
        evidence_refs=("reader:3",),
        validation_refs=("check:clarity",),
        consequence_notes=("Two sentences change.",),
        risk_notes=("The first sentence becomes less spare.",),
        root=root,
    )


def test_current_is_durable_and_digest_bound(tmp_path: Path) -> None:
    created = make_document(tmp_path)
    current = get_current("chapter-07", root=tmp_path)
    assert current["version_id"] == created["version_id"]
    assert current["content"] == CURRENT
    assert current["content_digest"] == content_digest(CURRENT)
    assert len(get_history("chapter-07", root=tmp_path)) == 1


def test_duplicate_document_and_unsafe_identity_are_rejected(tmp_path: Path) -> None:
    make_document(tmp_path)
    with pytest.raises(RevisionStudioError, match="already exists") as duplicate:
        make_document(tmp_path)
    assert duplicate.value.code == "document-already-exists"

    with pytest.raises(RevisionStudioError, match="document_id"):
        create_document(
            document_id="../escape",
            title="Unsafe",
            content="text",
            actor="Merrin",
            authority_ref="test",
            root=tmp_path,
        )


def test_assistant_proposal_does_not_change_current(tmp_path: Path) -> None:
    make_document(tmp_path)
    proposal = make_proposal(tmp_path)
    current = get_current("chapter-07", root=tmp_path)
    assert proposal["created_by_kind"] == "assistant"
    assert proposal["state"] == "proposed"
    assert current["content"] == CURRENT
    assert list_proposals("chapter-07", root=tmp_path) == [proposal]


def test_compare_exposes_exact_versions_diff_evidence_and_risk(tmp_path: Path) -> None:
    current = make_document(tmp_path)
    proposal = make_proposal(tmp_path)
    comparison = compare_proposal(
        "chapter-07", proposal["proposal_id"], root=tmp_path
    )
    assert comparison["current_version_id"] == current["version_id"]
    assert comparison["proposed_version_id"] == proposal["proposed_version_id"]
    assert "-The path crossed the field." in comparison["unified_diff"]
    assert "+The old path crossed the field." in comparison["unified_diff"]
    assert comparison["evidence_refs"] == ["reader:3"]
    assert comparison["risk_notes"] == ["The first sentence becomes less spare."]
    assert comparison["changed_units"]


def test_no_op_proposal_is_rejected(tmp_path: Path) -> None:
    make_document(tmp_path)
    with pytest.raises(RevisionStudioError, match="identical") as error:
        create_proposal(
            document_id="chapter-07",
            content=CURRENT,
            rationale="No change",
            created_by="assistant",
            created_by_kind="assistant",
            root=tmp_path,
        )
    assert error.value.code == "no-op-proposal"


def test_accept_all_requires_human_authority_and_changes_current(tmp_path: Path) -> None:
    original = make_document(tmp_path)
    proposal = make_proposal(tmp_path)

    with pytest.raises(RevisionStudioError, match="actor is required"):
        decide_proposal(
            document_id="chapter-07",
            proposal_id=proposal["proposal_id"],
            action="accept_all",
            actor=" ",
            authority_ref="test:authority",
            root=tmp_path,
        )

    resolution = decide_proposal(
        document_id="chapter-07",
        proposal_id=proposal["proposal_id"],
        action="accept_all",
        actor="Merrin",
        authority_ref="test:accept-all",
        root=tmp_path,
    )
    current = get_current("chapter-07", root=tmp_path)
    assert resolution["authoritative_changed"] is True
    assert resolution["retained_in_history"] is True
    assert current["version_id"] != original["version_id"]
    assert current["content"] == PROPOSED
    assert current["accepted_by"] == "Merrin"
    assert get_proposal(
        "chapter-07", proposal["proposal_id"], root=tmp_path
    )["state"] == "accepted"


def test_partial_acceptance_requires_proper_subset_and_actual_merge(tmp_path: Path) -> None:
    make_document(tmp_path)
    proposal = make_proposal(tmp_path)
    units = proposal["changed_units"]
    assert len(units) >= 2

    with pytest.raises(RevisionStudioError, match="proper subset"):
        decide_proposal(
            document_id="chapter-07",
            proposal_id=proposal["proposal_id"],
            action="accept_part",
            actor="Merrin",
            authority_ref="test:partial",
            accepted_units=units,
            merged_content=PARTIAL,
            root=tmp_path,
        )

    with pytest.raises(RevisionStudioError, match="distinct"):
        decide_proposal(
            document_id="chapter-07",
            proposal_id=proposal["proposal_id"],
            action="accept_part",
            actor="Merrin",
            authority_ref="test:partial",
            accepted_units=(units[0],),
            merged_content=PROPOSED,
            root=tmp_path,
        )

    resolution = decide_proposal(
        document_id="chapter-07",
        proposal_id=proposal["proposal_id"],
        action="accept_part",
        actor="Merrin",
        authority_ref="test:partial",
        accepted_units=(units[0],),
        merged_content=PARTIAL,
        root=tmp_path,
    )
    assert resolution["proposal_state"] == "partially_accepted"
    assert resolution["decision"]["accepted_units"] == [units[0]]
    assert set(resolution["decision"]["rejected_units"]) == set(units[1:])
    assert get_current("chapter-07", root=tmp_path)["content"] == PARTIAL


def test_keep_for_later_and_reject_preserve_current_and_proposal_history(
    tmp_path: Path,
) -> None:
    for document_id, action, expected_state in (
        ("keep", "keep_for_later", "kept_for_later"),
        ("reject", "reject", "rejected"),
    ):
        make_document(tmp_path, document_id)
        proposal = make_proposal(tmp_path, document_id)
        before = get_current(document_id, root=tmp_path)
        resolution = decide_proposal(
            document_id=document_id,
            proposal_id=proposal["proposal_id"],
            action=action,
            actor="Merrin",
            authority_ref=f"test:{action}",
            root=tmp_path,
        )
        after = get_current(document_id, root=tmp_path)
        retained = get_proposal(document_id, proposal["proposal_id"], root=tmp_path)
        assert resolution["authoritative_changed"] is False
        assert resolution["retained_in_history"] is True
        assert before["version_id"] == after["version_id"]
        assert retained["content"] == PROPOSED
        assert retained["state"] == expected_state


def test_stale_proposal_fails_closed_after_another_proposal_is_accepted(
    tmp_path: Path,
) -> None:
    make_document(tmp_path)
    first = make_proposal(tmp_path)
    second = create_proposal(
        document_id="chapter-07",
        content=CURRENT.replace("field", "meadow"),
        rationale="Alternative wording.",
        created_by="Merrin",
        created_by_kind="human",
        root=tmp_path,
    )
    decide_proposal(
        document_id="chapter-07",
        proposal_id=first["proposal_id"],
        action="accept_all",
        actor="Merrin",
        authority_ref="test:first-wins",
        root=tmp_path,
    )
    with pytest.raises(RevisionStudioError, match="stale") as error:
        compare_proposal("chapter-07", second["proposal_id"], root=tmp_path)
    assert error.value.status_code == 409


def test_proposal_cannot_receive_two_final_decisions(tmp_path: Path) -> None:
    make_document(tmp_path)
    proposal = make_proposal(tmp_path)
    decide_proposal(
        document_id="chapter-07",
        proposal_id=proposal["proposal_id"],
        action="reject",
        actor="Merrin",
        authority_ref="test:reject",
        root=tmp_path,
    )
    with pytest.raises(RevisionStudioError, match="already"):
        decide_proposal(
            document_id="chapter-07",
            proposal_id=proposal["proposal_id"],
            action="reject",
            actor="Merrin",
            authority_ref="test:again",
            root=tmp_path,
        )


def test_tampered_current_content_is_detected(tmp_path: Path) -> None:
    current = make_document(tmp_path)
    path = tmp_path / "chapter-07" / current["content_path"]
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(RevisionStudioError, match="digest") as error:
        get_current("chapter-07", root=tmp_path)
    assert error.value.code == "current-digest-mismatch"


def test_history_records_creation_proposal_and_decision(tmp_path: Path) -> None:
    make_document(tmp_path)
    proposal = make_proposal(tmp_path)
    decide_proposal(
        document_id="chapter-07",
        proposal_id=proposal["proposal_id"],
        action="keep_for_later",
        actor="Merrin",
        authority_ref="test:later",
        root=tmp_path,
    )
    history = get_history("chapter-07", root=tmp_path)
    assert [event["event"] for event in history] == [
        "current_created",
        "proposal_created",
        "proposal_decided",
    ]
    stored = json.loads(
        (tmp_path / "chapter-07" / "history.json").read_text(encoding="utf-8")
    )
    assert stored == history
