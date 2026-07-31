# v0.2 Manuscript Validation API

## Authority

This document implements the first bounded capability under issue #64 from the immutable hardened baseline:

```text
v0.1.8-hardened
2594ffbab0c2c7773bfac8a6e562f6e98bb98761
```

The v0.1 deterministic publishing core remains complete. This endpoint is a separate v0.2 capability.

## Endpoint

```text
POST /api/v1/validate
```

Production requests use the existing API-key authentication:

```text
X-API-Key: <configured BOOK_API_KEY>
```

## Request

```json
{
  "title": "Optional request title",
  "content": "---\ntitle: Example\nlang: en-GB\n---\n\n# Opening\n\nText."
}
```

`content` must be a JSON string. A missing field or wrong type is a malformed request and returns FastAPI's controlled HTTP 422 response.

An empty or whitespace-only string is a valid request but an invalid manuscript. It returns HTTP 200 with `valid: false`.

## Response

A completed validation returns HTTP 200 whether the manuscript is valid or invalid:

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "summary": {
    "request_title": "Optional request title",
    "source_bytes": 72,
    "normalised_bytes": 72,
    "normalisation_changed": false,
    "metadata_fields": ["lang", "title"],
    "block_count": 2,
    "heading_count": 1,
    "level_one_heading_count": 1,
    "maximum_heading_level": 1,
    "image_count": 0,
    "table_count": 0,
    "footnote_count": 0,
    "list_count": 0,
    "raw_content_count": 0
  },
  "contract_version": "0.2"
}
```

Each finding contains:

- `code`: stable machine-readable identifier;
- `severity`: `error` or `warning`;
- `message`: concise human-readable explanation;
- `location`: optional bounded structural location when available.

Initial error codes include:

- `empty-manuscript`;
- `manuscript-parse-error`.

Initial warning codes include:

- `no-headings`;
- `starts-below-level-one`;
- `heading-level-jump`;
- `raw-format-content`;
- `title-metadata-missing`;
- `language-metadata-missing`;
- `pandoc-parser-warning`.

A metadata key with an empty string, empty inline sequence, empty block sequence, empty list or empty map is treated as missing for the title and language checks. `metadata_fields` still records the declared key so callers can distinguish an absent key from an empty one.

## Controlled non-200 responses

Transport, authentication, configuration, resource and validation-tool failures remain HTTP failures. Examples include:

- `403` for a missing or incorrect API key;
- `413 request-too-large`;
- `413 manuscript-too-large`;
- `422` for a malformed JSON request;
- `503 validation-tool-unavailable`;
- `503 validation-timeout`;
- `503 validation-tool-failed`;
- `503 validation-tool-invalid-response`.

Pandoc exit code `64` is treated as a manuscript parse error and therefore returns a completed HTTP 200 validation result with `valid: false`. Other non-zero Pandoc exits are treated as validation-tool failures and return the sanitised `503 validation-tool-failed` response. Pandoc stderr is never copied into the public response.

## Deterministic implementation

Validation:

1. applies the authoritative conservative Markdown normalisation;
2. checks the existing configured manuscript byte limit;
3. sends the normalised Markdown to Pandoc through standard input;
4. uses `markdown+yaml_metadata_block` and Pandoc's JSON AST;
5. runs Pandoc in sandbox mode with a maximum of 30 seconds and never longer than the configured export-command timeout;
6. distinguishes manuscript parse failure from tool, option, internal and resource failures;
7. derives a bounded structural summary and stable findings.

The endpoint does not create a job directory, lock, status record, history event, output, manifest or persistent manuscript copy. The existing request-body middleware applies before authentication parsing and validation execution.

## Exclusions

This endpoint does not:

- generate or rewrite prose;
- perform editorial judgement;
- implement Semantic Architect behaviour;
- submit a publishing job;
- create PDF, EPUB or DOCX output;
- implement executable `/api/v1/publish*` job routes;
- add print-production, cover, spine, bleed, colour or imposition behaviour;
- authorise production deployment.

The publish dry-run route is documented separately in
`docs/V0_2_PUBLISH_DRY_RUN_API.md` and reuses this validation service without
creating jobs or rendering outputs.
