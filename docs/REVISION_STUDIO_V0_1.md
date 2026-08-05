# Revision Studio foundation v0.1

## Governing rule

> Make experimentation safe, preserve the accepted manuscript, and turn acceptance into an explicit human act.

Revision Studio adopts Threadkeeper Proposal and Acceptance Protocol v0.1 for manuscripts. It separates the accepted manuscript from alternative revisions and records every final decision without deleting rejected or deferred work.

## Vocabulary

- **Current** — the accepted manuscript version.
- **Proposed** — an alternative bound to the exact Current version and digest.
- **Compare** — a deterministic unified diff plus evidence, validation, consequences and risks.
- **Accept** — a human decision to accept all or part of Proposed.
- **Keep for later** — preserve Proposed without changing Current.
- **Reject** — decline Proposed without deleting it.
- **History** — manuscript creation, proposals and final decisions.

## Storage

Records are stored below the configured `BOOK_SYSTEM_ROOT`:

```text
books/revisions/<document_id>/
├── current.json
├── history.json
├── versions/
│   └── <version_id>.md
└── proposals/
    └── <proposal_id>/
        ├── proposal.json
        ├── proposed.md
        └── decision.json
```

Manuscript content is SHA-256 bound. A missing or altered Current or Proposed file fails closed.

## API

Every route requires the existing Book System API-key dependency.

### Create Current

`POST /api/v1/revisions/documents`

```json
{
  "document_id": "chapter-07",
  "title": "Chapter Seven",
  "content": "# Chapter Seven\n",
  "actor": "Merrin",
  "authority_ref": "owner:initial-acceptance"
}
```

### Read Current

`GET /api/v1/revisions/documents/{document_id}`

### Create Proposed

`POST /api/v1/revisions/documents/{document_id}/proposals`

```json
{
  "content": "# Chapter Seven\n\nRevised text.\n",
  "rationale": "Clarify the route.",
  "created_by": "clarity-assistant",
  "created_by_kind": "assistant",
  "evidence_refs": ["reader:3"],
  "validation_refs": ["check:clarity"],
  "consequence_notes": ["One paragraph changes."],
  "risk_notes": ["The cadence may become less spare."]
}
```

Human, assistant, automation and import actors may create Proposed. None of those creator labels grant acceptance authority.

### List and inspect Proposed

- `GET /api/v1/revisions/documents/{document_id}/proposals`
- `GET /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}`
- `GET /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}/compare`

### Decide

`POST /api/v1/revisions/documents/{document_id}/proposals/{proposal_id}/decision`

Accept all:

```json
{
  "action": "accept_all",
  "actor": "Merrin",
  "authority_ref": "owner:accepted"
}
```

Accept part:

```json
{
  "action": "accept_part",
  "actor": "Merrin",
  "authority_ref": "owner:partial-acceptance",
  "accepted_units": ["change-002"],
  "merged_content": "# Chapter Seven\n\nThe actual merged result.\n"
}
```

Partial acceptance must select a non-empty proper subset of the changed units and supply the actual merged manuscript. The result must differ from both Current and the untouched Proposed manuscript.

Keep for later and reject use `keep_for_later` and `reject`. Neither changes Current.

### History

`GET /api/v1/revisions/documents/{document_id}/history`

## Safety rules

- Creating Proposed never changes Current.
- Decisions require a non-blank human actor and authority reference.
- A proposal becomes stale when Current no longer matches its base version and digest.
- A proposal receives only one final decision.
- Rejected and deferred proposal content remains available.
- Partial acceptance cannot pretend the complete proposal was accepted.
- Publication, export and deployment remain separate protected actions.

## v0.1 boundary

This unit supplies durable storage, comparison, decisions, history and authenticated APIs. It does not yet provide the visual Revision Studio, collaborative accounts, comments, paragraph-level interactive merging, whole-book branch navigation or publication from a proposal.
