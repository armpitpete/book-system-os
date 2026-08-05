# Portable Revision Studio package v0.1

## Purpose

A revision document must remain usable without Book System OS. The portable package exports the accepted manuscript, every retained alternative and the decision record as ordinary files inside a deterministic ZIP archive.

## Download

Dashboard:

- open a revision document;
- open **History**;
- choose **Download portable package**.

Authenticated API:

```text
GET /api/v1/revisions/documents/{document_id}/package
```

The response includes:

- `Content-Disposition` with the package filename;
- `X-Content-SHA256` for the complete ZIP archive;
- `X-Revision-Package-Version: 0.1`.

## Package layout

```text
README.md
manifest.json
revision/
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

A proposal without a final decision legitimately has no `decision.json`.

## Preservation rules

- Current is exported with its exact version and SHA-256 digest.
- Accepted manuscript versions remain readable Markdown files.
- Rejected and kept-for-later proposals are retained.
- Proposal content does not become accepted merely because it is present.
- History records creation, proposal and decision events.
- Export does not publish, render, delete or mutate the revision document.

## Verification

`manifest.json` records the size and SHA-256 digest of every payload file and `README.md`. It intentionally excludes itself to avoid a circular self-hash. The download response provides the SHA-256 digest of the complete ZIP archive.

Authenticated verification API:

```text
POST /api/v1/revisions/package/verify
Content-Type: multipart/form-data
Field: package
```

The verifier rejects:

- unreadable archives;
- absolute paths or `..` traversal;
- duplicate paths;
- symbolic links;
- unsupported package versions;
- missing or repeated manifest entries;
- changed file sizes or SHA-256 digests;
- unrecorded payload files.

## Reproducibility

Archive member order, permissions and timestamps are fixed. Exporting unchanged revision state produces identical ZIP bytes and the same complete-archive SHA-256 digest.

## Boundary

This package is a revision and provenance export. It is not PDF, EPUB, DOCX or publication output, and it does not include external accounts, deployment state or secrets.
