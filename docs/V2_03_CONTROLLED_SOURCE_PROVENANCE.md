# V2-03 Controlled Source Identity and Derivation Manifest

## Scope

V2-03 adds internal source-provenance support to Book System OS. It does not add a public controlled-publish route, repository fetching, credentials, manuscript rewriting, editorial approval logic, accounts, billing or print-production behaviour.

Existing dashboard and API callers continue to create uncontrolled jobs. A future internal caller may supply the controlled source record described below.

## Controlled source record v1

A controlled source record is a producer-supplied assertion about one exact Markdown source:

```json
{
  "schema_version": "1",
  "canonical_path": "manuscript/book.md",
  "source_sha256": "<64 lowercase hexadecimal characters>",
  "source_bytes": 1234,
  "source_commit": "<immutable source commit identifier>",
  "source_blob": null,
  "control_file_version": "<stable version or digest>",
  "review_state": "<producer-supplied state>",
  "publication_state": "<producer-supplied state>"
}
```

Validation is strict. Unknown fields, type coercion, unsafe paths, control characters, unsupported schema versions and oversized values are rejected as `control-record-invalid`.

Before any job directory is created, Book System OS encodes the submitted Markdown as UTF-8 and checks:

1. exact byte count;
2. exact SHA-256 digest.

Byte-count failure takes precedence and returns `source-bytes-mismatch`. A same-length digest failure returns `source-sha256-mismatch`.

The complete validated record receives a deterministic SHA-256 identity calculated from canonical UTF-8 JSON with sorted keys, compact separators and `source_blob: null` retained explicitly.

## Verified facts and retained assertions

Book System OS verifies locally:

- the exact submitted UTF-8 bytes;
- the submitted byte count;
- the submitted SHA-256 digest;
- the retained `input/book.md` bytes before pipeline work and retry;
- the cleaned Markdown bytes and digest;
- each generated output's filename, media type, byte size and digest.

Book System OS retains but does not independently verify:

- canonical repository path;
- source commit identifier;
- optional source blob identifier;
- control-file version;
- review state;
- publication state.

Those values remain producer assertions. Human editorial, readability, accessibility and publication decisions remain outside the software's authority.

## New-job metadata

Every new job records `source_identity` in `metadata.json`, whether or not a controlled record was supplied:

```json
{
  "source_identity": {
    "schema_version": "1",
    "source_bytes": 1234,
    "source_sha256": "...",
    "controlled": true,
    "control_record_sha256": "...",
    "control_record": {}
  }
}
```

Uncontrolled jobs retain locally calculated bytes and SHA-256 with `controlled: false`, `control_record_sha256: null` and `control_record: null`.

Identity-bearing Markdown is written and read as bytes so platform newline translation cannot change the retained source.

## Derivation manifest v2

A successful new pipeline run writes `manifest.json` with:

- `schema_version: "2"`;
- completion timestamp and final status;
- the existing `outputs` key-to-filename mapping;
- provenance availability state;
- immutable source identity copied from job metadata;
- cleaned Markdown byte size and SHA-256;
- structural-cleanup transformation identifier and version;
- ordered `output_evidence` generated from `PUBLISH_OUTPUTS`.

Each output-evidence entry contains:

```json
{
  "key": "pdf_standard",
  "filename": "book-standard.pdf",
  "media_type": "application/pdf",
  "bytes": 12345,
  "sha256": "..."
}
```

The original `outputs` mapping remains present for backup validation, rollback integrity snapshots, authenticated download verification and existing consumers. `PUBLISH_OUTPUTS` remains the only filename and media-type authority.

## Tamper and retry behaviour

Before structural cleanup or export, and before a failed job is retried, Book System OS recomputes the retained `input/book.md` identity.

A mismatch:

- fails closed;
- does not rewrite immutable metadata;
- records `step: source-integrity` and a stable `failure_code`;
- appends a `source-integrity-failed` event;
- prevents cleanup/export or retry-directory replacement.

An unchanged retry preserves `metadata.json` and `input/book.md` and replaces only the existing retryable `work`, `logs` and `output` directories.

## Staleness assessment

`assess_manifest_staleness` is an internal pure function. It compares supplied current controlled authority with retained manifest evidence only. It performs no network, GitHub or external repository access.

It returns:

```json
{"current": true, "reasons": []}
```

or a deterministic ordered reason list, for example:

```json
{"current": false, "reasons": ["source-sha256-changed"]}
```

## Legacy jobs

Retained jobs without `source_identity` remain valid historical jobs. They are reported as:

```text
provenance_unavailable
```

They are not rewritten, migrated or classified as corrupt. Existing backup, restore, integrity, cleanup, archive, dashboard and download behaviour remains compatible.

## Route boundary

V2-03 does not implement:

```text
POST /api/v1/publish
```

It also does not implement publish status, list or retry routes. Controlled source support remains an internal capability until a later separately authorised contract.
