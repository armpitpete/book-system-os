# v0.2 Publish Dry-Run API

## Authority

This document covers the bounded publish dry-run capability introduced under issue
#78 from the accepted V2-01 base:

```text
b40ebf0d654877cb078bffb5fec6b18b856b95b9
```

The route plans the existing deterministic four-format production output set. It
does not create or run a publish job.

## Endpoint

```text
POST /api/v1/publish/dry-run
```

Production requests use the existing API-key authentication:

```text
X-API-Key: <configured BOOK_API_KEY>
```

The route appears in `/api/v1/status` under `implemented`. The executable publish
routes remain under `not_yet_implemented`.

## Request

```json
{
  "title": "Optional request title",
  "content": "---\ntitle: Example\nlang: en-GB\n---\n\n# Opening\n\nText."
}
```

`content` must be a JSON string. A missing field or wrong type is a malformed
request and returns FastAPI's controlled HTTP 422 response.

An empty or whitespace-only string is a valid request but a non-publishable
manuscript. It returns HTTP 200 with `publishable: false`.

## Response

A completed dry run returns HTTP 200 whether the manuscript is publishable or
non-publishable:

```json
{
  "publishable": true,
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": [],
    "summary": {
      "request_title": "Optional request title",
      "source_bytes": 52,
      "normalised_bytes": 53,
      "normalisation_changed": true,
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
  },
  "outputs": [
    {
      "key": "pdf_standard",
      "filename": "book-standard.pdf",
      "media_type": "application/pdf"
    },
    {
      "key": "pdf_nd",
      "filename": "book-nd.pdf",
      "media_type": "application/pdf"
    },
    {
      "key": "epub",
      "filename": "book.epub",
      "media_type": "application/epub+zip"
    },
    {
      "key": "docx",
      "filename": "book.docx",
      "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
  ],
  "source_bytes": 52,
  "source_sha256": "22b4ea016b1726adfca25f8f2c60c5ed90db347fbf7c2158cc36df7c77d8e58e",
  "job_state": "production",
  "rendering_attempted": false,
  "job_created": false,
  "contract_version": "0.2"
}
```

The output list is generated from the same authoritative output specification
consumed by `pandoc_export`. The current output contract is:

| key | filename | media_type |
|---|---|---|
| `pdf_standard` | `book-standard.pdf` | `application/pdf` |
| `pdf_nd` | `book-nd.pdf` | `application/pdf` |
| `epub` | `book.epub` | `application/epub+zip` |
| `docx` | `book.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |

## Controlled non-200 responses

Transport, authentication, configuration, resource and validation-tool failures
remain HTTP failures. Examples include:

- `403` for a missing or incorrect API key;
- `413 request-too-large`;
- `413 manuscript-too-large`;
- `422` for a malformed JSON request;
- `503 validation-tool-unavailable`;
- `503 validation-timeout`;
- `503 validation-tool-failed`;
- `503 validation-tool-invalid-response`.

Pandoc exit code `64` remains a manuscript parse error and therefore returns a
completed HTTP 200 dry-run result with `publishable: false`. Other non-zero
Pandoc exits remain validation-tool failures and return the sanitised HTTP 503
response. Pandoc stderr is never copied into the public response.

## Side-effect boundary

Dry-run validation:

1. applies the existing request body and manuscript byte limits;
2. calls the existing manuscript validation service;
3. computes `source_bytes` and `source_sha256` from the submitted UTF-8 content;
4. returns the authoritative four-output plan.

The route does not create a job directory, queue entry, lock, history record, log
directory, output directory, manifest, retained manuscript copy, temporary
manuscript copy, worker activity or export subprocess. The existing sandboxed
validation subprocess remains permitted.

## Exclusions

This endpoint does not:

- submit a publishing job;
- create PDF, EPUB or DOCX output;
- implement `/api/v1/publish`;
- implement publish status, list or retry routes;
- add print-production, cover, spine, bleed, colour or imposition behaviour;
- implement Semantic Architect behaviour;
- authorise production deployment.
