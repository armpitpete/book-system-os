from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence

from app.utils.atomic_files import atomic_write_json, atomic_write_text
from app.utils.paths import repo_root

DecisionAction = Literal["accept_all", "accept_part", "keep_for_later", "reject"]
ProposalState = Literal[
    "proposed", "accepted", "partially_accepted", "kept_for_later", "rejected"
]

SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class RevisionStudioError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def payload(self) -> dict[str, str]:
        return {"error": self.code, "message": str(self)}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def revision_root() -> Path:
    path = repo_root() / "books" / "revisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: str, field: str) -> str:
    cleaned = value.strip()
    if not SAFE_ID.fullmatch(cleaned):
        raise RevisionStudioError(
            f"{field} must use 1-128 letters, numbers, dots, dashes or underscores.",
            code=f"invalid-{field.replace('_', '-')}",
        )
    return cleaned


def _require_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise RevisionStudioError(f"{field} is required.", code=f"missing-{field.replace('_', '-')}")
    return cleaned


def _document_dir(document_id: str, *, root: Path | None = None) -> Path:
    safe = _safe_id(document_id, "document_id")
    return (root or revision_root()) / safe


def _current_path(document_dir: Path) -> Path:
    return document_dir / "current.json"


def _history_path(document_dir: Path) -> Path:
    return document_dir / "history.json"


def _version_path(document_dir: Path, version_id: str) -> Path:
    return document_dir / "versions" / f"{_safe_id(version_id, 'version_id')}.md"


def _proposal_dir(document_dir: Path, proposal_id: str) -> Path:
    return document_dir / "proposals" / _safe_id(proposal_id, "proposal_id")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RevisionStudioError(
            f"Record not found: {path.name}", code="not-found", status_code=404
        ) from exc
    except json.JSONDecodeError as exc:
        raise RevisionStudioError(
            f"Stored record is invalid: {path.name}",
            code="invalid-stored-record",
            status_code=500,
        ) from exc
    if not isinstance(value, dict):
        raise RevisionStudioError(
            f"Stored record is invalid: {path.name}",
            code="invalid-stored-record",
            status_code=500,
        )
    return value


def _read_history(document_dir: Path) -> list[dict[str, Any]]:
    path = _history_path(document_dir)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RevisionStudioError(
            "Stored revision history is invalid.",
            code="invalid-stored-history",
            status_code=500,
        ) from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RevisionStudioError(
            "Stored revision history is invalid.",
            code="invalid-stored-history",
            status_code=500,
        )
    return value


def _append_history(document_dir: Path, event: dict[str, Any]) -> None:
    history = _read_history(document_dir)
    history.append(event)
    atomic_write_json(_history_path(document_dir), history, sort_keys=True)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _changed_units(current: str, proposed: str) -> tuple[str, ...]:
    matcher = difflib.SequenceMatcher(
        a=current.splitlines(), b=proposed.splitlines(), autojunk=False
    )
    units: list[str] = []
    for index, (tag, _a1, _a2, _b1, _b2) in enumerate(matcher.get_opcodes(), start=1):
        if tag != "equal":
            units.append(f"change-{index:03d}")
    return tuple(units)


def _unified_diff(current: str, proposed: str) -> str:
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile="Current",
            tofile="Proposed",
            lineterm="\n",
        )
    )


def create_document(
    *,
    document_id: str,
    title: str,
    content: str,
    actor: str,
    authority_ref: str,
    root: Path | None = None,
) -> dict[str, Any]:
    document_dir = _document_dir(document_id, root=root)
    if _current_path(document_dir).exists():
        raise RevisionStudioError(
            "A Current manuscript already exists for this document.",
            code="document-already-exists",
            status_code=409,
        )
    clean_title = _require_text(title, "title")
    clean_actor = _require_text(actor, "actor")
    clean_authority = _require_text(authority_ref, "authority_ref")
    if not content:
        raise RevisionStudioError("content is required.", code="missing-content")

    version_id = _new_id("version")
    digest = content_digest(content)
    created_at = utc_now()
    current = {
        "document_id": _safe_id(document_id, "document_id"),
        "title": clean_title,
        "version_id": version_id,
        "content_digest": digest,
        "content_path": f"versions/{version_id}.md",
        "accepted_by": clean_actor,
        "authority_ref": clean_authority,
        "accepted_at": created_at,
    }
    atomic_write_text(_version_path(document_dir, version_id), content)
    atomic_write_json(_current_path(document_dir), current, sort_keys=True)
    _append_history(
        document_dir,
        {
            "event": "current_created",
            "created_at": created_at,
            "version_id": version_id,
            "content_digest": digest,
            "actor": clean_actor,
            "authority_ref": clean_authority,
        },
    )
    return {**current, "content": content}


def get_current(document_id: str, *, root: Path | None = None) -> dict[str, Any]:
    document_dir = _document_dir(document_id, root=root)
    current = _read_json(_current_path(document_dir))
    version_path = document_dir / str(current.get("content_path", ""))
    try:
        content = version_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RevisionStudioError(
            "The Current manuscript content is missing.",
            code="current-content-missing",
            status_code=500,
        ) from exc
    digest = content_digest(content)
    if digest != current.get("content_digest"):
        raise RevisionStudioError(
            "The Current manuscript digest does not match its content.",
            code="current-digest-mismatch",
            status_code=500,
        )
    return {**current, "content": content}


def create_proposal(
    *,
    document_id: str,
    content: str,
    rationale: str,
    created_by: str,
    created_by_kind: Literal["human", "assistant", "automation", "import"],
    evidence_refs: Sequence[str] = (),
    validation_refs: Sequence[str] = (),
    consequence_notes: Sequence[str] = (),
    risk_notes: Sequence[str] = (),
    root: Path | None = None,
) -> dict[str, Any]:
    current = get_current(document_id, root=root)
    if not content:
        raise RevisionStudioError("content is required.", code="missing-content")
    proposed_digest = content_digest(content)
    if proposed_digest == current["content_digest"]:
        raise RevisionStudioError(
            "Proposed content is identical to Current.", code="no-op-proposal"
        )
    if created_by_kind not in {"human", "assistant", "automation", "import"}:
        raise RevisionStudioError(
            "created_by_kind is not recognised.", code="invalid-created-by-kind"
        )

    changed_units = _changed_units(current["content"], content)
    if not changed_units:
        raise RevisionStudioError(
            "Proposal contains no detectable change.", code="no-op-proposal"
        )

    proposal_id = _new_id("proposal")
    proposed_version_id = _new_id("version")
    proposal_dir = _proposal_dir(
        _document_dir(document_id, root=root), proposal_id
    )
    created_at = utc_now()
    record = {
        "proposal_id": proposal_id,
        "document_id": current["document_id"],
        "base_version_id": current["version_id"],
        "base_digest": current["content_digest"],
        "proposed_version_id": proposed_version_id,
        "proposed_digest": proposed_digest,
        "created_by": _require_text(created_by, "created_by"),
        "created_by_kind": created_by_kind,
        "created_at": created_at,
        "rationale": _require_text(rationale, "rationale"),
        "changed_units": list(changed_units),
        "evidence_refs": [value.strip() for value in evidence_refs if value.strip()],
        "validation_refs": [value.strip() for value in validation_refs if value.strip()],
        "consequence_notes": [value.strip() for value in consequence_notes if value.strip()],
        "risk_notes": [value.strip() for value in risk_notes if value.strip()],
        "state": "proposed",
    }
    atomic_write_text(proposal_dir / "proposed.md", content)
    atomic_write_json(proposal_dir / "proposal.json", record, sort_keys=True)
    _append_history(
        _document_dir(document_id, root=root),
        {
            "event": "proposal_created",
            "created_at": created_at,
            "proposal_id": proposal_id,
            "base_version_id": current["version_id"],
            "proposed_version_id": proposed_version_id,
            "created_by": record["created_by"],
            "created_by_kind": created_by_kind,
        },
    )
    return record


def get_proposal(
    document_id: str, proposal_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    proposal_dir = _proposal_dir(_document_dir(document_id, root=root), proposal_id)
    record = _read_json(proposal_dir / "proposal.json")
    try:
        content = (proposal_dir / "proposed.md").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RevisionStudioError(
            "The Proposed manuscript content is missing.",
            code="proposal-content-missing",
            status_code=500,
        ) from exc
    if content_digest(content) != record.get("proposed_digest"):
        raise RevisionStudioError(
            "The Proposed manuscript digest does not match its content.",
            code="proposal-digest-mismatch",
            status_code=500,
        )
    decision_path = proposal_dir / "decision.json"
    decision = _read_json(decision_path) if decision_path.exists() else None
    return {**record, "content": content, "decision": decision}


def list_proposals(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    document_dir = _document_dir(document_id, root=root)
    proposals_dir = document_dir / "proposals"
    if not proposals_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(proposals_dir.iterdir(), key=lambda item: item.name):
        if path.is_dir() and (path / "proposal.json").is_file():
            record = _read_json(path / "proposal.json")
            records.append(record)
    return records


def compare_proposal(
    document_id: str, proposal_id: str, *, root: Path | None = None
) -> dict[str, Any]:
    current = get_current(document_id, root=root)
    proposal = get_proposal(document_id, proposal_id, root=root)
    if proposal["base_version_id"] != current["version_id"]:
        raise RevisionStudioError(
            "Proposal is stale because Current has moved to another version.",
            code="stale-proposal",
            status_code=409,
        )
    if proposal["base_digest"] != current["content_digest"]:
        raise RevisionStudioError(
            "Proposal is stale because the Current digest changed.",
            code="stale-proposal",
            status_code=409,
        )
    return {
        "document_id": current["document_id"],
        "proposal_id": proposal["proposal_id"],
        "current_version_id": current["version_id"],
        "current_digest": current["content_digest"],
        "proposed_version_id": proposal["proposed_version_id"],
        "proposed_digest": proposal["proposed_digest"],
        "changed_units": proposal["changed_units"],
        "unified_diff": _unified_diff(current["content"], proposal["content"]),
        "evidence_refs": proposal["evidence_refs"],
        "validation_refs": proposal["validation_refs"],
        "consequence_notes": proposal["consequence_notes"],
        "risk_notes": proposal["risk_notes"],
    }


def decide_proposal(
    *,
    document_id: str,
    proposal_id: str,
    action: DecisionAction,
    actor: str,
    authority_ref: str,
    accepted_units: Sequence[str] = (),
    merged_content: str | None = None,
    note: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    document_dir = _document_dir(document_id, root=root)
    current = get_current(document_id, root=root)
    proposal = get_proposal(document_id, proposal_id, root=root)
    if proposal["state"] != "proposed" or proposal.get("decision") is not None:
        raise RevisionStudioError(
            "Proposal already has a final decision.",
            code="proposal-already-decided",
            status_code=409,
        )
    compare_proposal(document_id, proposal_id, root=root)
    if action not in {"accept_all", "accept_part", "keep_for_later", "reject"}:
        raise RevisionStudioError("Decision action is not recognised.", code="invalid-action")

    clean_actor = _require_text(actor, "actor")
    clean_authority = _require_text(authority_ref, "authority_ref")
    if note is not None and not note.strip():
        raise RevisionStudioError("note must be omitted or non-blank.", code="invalid-note")

    all_units = tuple(str(unit) for unit in proposal["changed_units"])
    accepted = tuple(dict.fromkeys(unit.strip() for unit in accepted_units if unit.strip()))
    if set(accepted) - set(all_units):
        raise RevisionStudioError(
            "accepted_units contains a unit outside this proposal.",
            code="invalid-accepted-units",
        )

    next_current: dict[str, Any] | None = None
    rejected: tuple[str, ...] = ()
    if action == "accept_all":
        if accepted or merged_content is not None:
            raise RevisionStudioError(
                "accept_all must not include partial-acceptance fields.",
                code="invalid-accept-all",
            )
        accepted = all_units
        version_id = proposal["proposed_version_id"]
        content = proposal["content"]
        state: ProposalState = "accepted"
    elif action == "accept_part":
        if not accepted or set(accepted) == set(all_units):
            raise RevisionStudioError(
                "accept_part requires a non-empty proper subset of changed units.",
                code="invalid-partial-selection",
            )
        if merged_content is None or not merged_content:
            raise RevisionStudioError(
                "accept_part requires the actual merged content.",
                code="missing-merged-content",
            )
        merged_digest = content_digest(merged_content)
        if merged_digest in {current["content_digest"], proposal["proposed_digest"]}:
            raise RevisionStudioError(
                "Partial acceptance must produce content distinct from Current and Proposed.",
                code="invalid-partial-result",
            )
        version_id = _new_id("version")
        content = merged_content
        rejected = tuple(unit for unit in all_units if unit not in set(accepted))
        state = "partially_accepted"
    elif action == "keep_for_later":
        if accepted or merged_content is not None:
            raise RevisionStudioError(
                "keep_for_later must not include acceptance fields.",
                code="invalid-keep-for-later",
            )
        version_id = ""
        content = ""
        state = "kept_for_later"
    else:
        if accepted or merged_content is not None:
            raise RevisionStudioError(
                "reject must not include acceptance fields.", code="invalid-reject"
            )
        version_id = ""
        content = ""
        rejected = all_units
        state = "rejected"

    decided_at = utc_now()
    if action in {"accept_all", "accept_part"}:
        digest = content_digest(content)
        atomic_write_text(_version_path(document_dir, version_id), content)
        next_current = {
            "document_id": current["document_id"],
            "title": current["title"],
            "version_id": version_id,
            "content_digest": digest,
            "content_path": f"versions/{version_id}.md",
            "accepted_by": clean_actor,
            "authority_ref": clean_authority,
            "accepted_at": decided_at,
            "source_proposal_id": proposal_id,
        }
        atomic_write_json(_current_path(document_dir), next_current, sort_keys=True)

    decision = {
        "decision_id": _new_id("decision"),
        "proposal_id": proposal_id,
        "action": action,
        "actor": clean_actor,
        "actor_kind": "human",
        "authority_ref": clean_authority,
        "decided_at": decided_at,
        "accepted_units": list(accepted),
        "rejected_units": list(rejected),
        "result_version_id": next_current["version_id"] if next_current else None,
        "result_digest": next_current["content_digest"] if next_current else None,
        "note": note.strip() if note is not None else None,
    }
    proposal_record = {key: value for key, value in proposal.items() if key not in {"content", "decision"}}
    proposal_record["state"] = state
    proposal_dir = _proposal_dir(document_dir, proposal_id)
    atomic_write_json(proposal_dir / "proposal.json", proposal_record, sort_keys=True)
    atomic_write_json(proposal_dir / "decision.json", decision, sort_keys=True)
    _append_history(
        document_dir,
        {
            "event": "proposal_decided",
            "created_at": decided_at,
            "proposal_id": proposal_id,
            "action": action,
            "state": state,
            "actor": clean_actor,
            "authority_ref": clean_authority,
            "previous_version_id": current["version_id"],
            "result_version_id": decision["result_version_id"],
            "accepted_units": list(accepted),
            "rejected_units": list(rejected),
        },
    )
    return {
        "proposal_id": proposal_id,
        "proposal_state": state,
        "authoritative_changed": next_current is not None,
        "retained_in_history": True,
        "previous_version_id": current["version_id"],
        "next_current": ({**next_current, "content": content} if next_current else None),
        "decision": decision,
    }


def get_history(document_id: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    return _read_history(_document_dir(document_id, root=root))
