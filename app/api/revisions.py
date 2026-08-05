from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.auth import api_key_required
from app.services.revision_studio import (
    compare_proposal,
    create_document,
    create_proposal,
    decide_proposal,
    get_current,
    get_history,
    get_proposal,
    list_proposals,
)

router = APIRouter(
    prefix="/api/v1/revisions",
    tags=["Revision Studio"],
    dependencies=[Depends(api_key_required)],
)


class CreateDocumentRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    actor: str = Field(min_length=1, max_length=200)
    authority_ref: str = Field(min_length=1, max_length=500)


class CreateProposalRequest(BaseModel):
    content: str = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)
    created_by: str = Field(min_length=1, max_length=200)
    created_by_kind: Literal["human", "assistant", "automation", "import"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    validation_refs: list[str] = Field(default_factory=list, max_length=100)
    consequence_notes: list[str] = Field(default_factory=list, max_length=100)
    risk_notes: list[str] = Field(default_factory=list, max_length=100)


class ProposalDecisionRequest(BaseModel):
    action: Literal["accept_all", "accept_part", "keep_for_later", "reject"]
    actor: str = Field(min_length=1, max_length=200)
    authority_ref: str = Field(min_length=1, max_length=500)
    accepted_units: list[str] = Field(default_factory=list, max_length=500)
    merged_content: str | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.post("/documents", status_code=201)
def api_create_revision_document(payload: CreateDocumentRequest) -> dict:
    return create_document(**payload.model_dump())


@router.get("/documents/{document_id}")
def api_get_revision_document(document_id: str) -> dict:
    return get_current(document_id)


@router.post("/documents/{document_id}/proposals", status_code=201)
def api_create_revision_proposal(
    document_id: str, payload: CreateProposalRequest
) -> dict:
    return create_proposal(document_id=document_id, **payload.model_dump())


@router.get("/documents/{document_id}/proposals")
def api_list_revision_proposals(document_id: str) -> dict[str, list[dict]]:
    return {"proposals": list_proposals(document_id)}


@router.get("/documents/{document_id}/proposals/{proposal_id}")
def api_get_revision_proposal(document_id: str, proposal_id: str) -> dict:
    return get_proposal(document_id, proposal_id)


@router.get("/documents/{document_id}/proposals/{proposal_id}/compare")
def api_compare_revision_proposal(document_id: str, proposal_id: str) -> dict:
    return compare_proposal(document_id, proposal_id)


@router.post("/documents/{document_id}/proposals/{proposal_id}/decision")
def api_decide_revision_proposal(
    document_id: str,
    proposal_id: str,
    payload: ProposalDecisionRequest,
) -> dict:
    return decide_proposal(
        document_id=document_id,
        proposal_id=proposal_id,
        **payload.model_dump(),
    )


@router.get("/documents/{document_id}/history")
def api_revision_history(document_id: str) -> dict[str, list[dict]]:
    return {"history": get_history(document_id)}
