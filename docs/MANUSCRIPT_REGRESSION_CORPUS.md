# Manuscript regression corpus

This document governs H-08 under issues #31 and #41.

The corpus proves representative deterministic export behaviour. It does not approve editorial quality, printer-specific production or new product features.

## Corpus files

The machine-readable index is:

```text
tests/fixtures/h08/corpus.json
```

The committed manuscript fixtures are:

```text
tests/fixtures/h08/representative.md
tests/fixtures/h08/malformed-yaml.md
```

The representative fixture is rendered deterministically during the test:

- an image is generated as a small valid PNG;
- a fixed twenty-chapter block is inserted;
- the final source remains below the accepted manuscript-size limit;
- no random data, network resource or current timestamp enters the manuscript.

## Required valid coverage

The representative manuscript covers:

- long chapters;
- Unicode and publishing punctuation;
- an embedded image;
- a table;
- a footnote;
- nested lists;
- a page break;
- YAML metadata;
- an unusual heading depth;
- a large but accepted source;
- format-specific raw HTML that may be omitted by formats that cannot represent it.

One representative source is used rather than many independent four-format jobs. This keeps CI bounded while exercising feature interaction.

## Output checks

The integration test requires all four outputs:

```text
book-standard.pdf
book-nd.pdf
book.epub
book.docx
```

The checks are intentionally basic and deterministic:

- each output exists and is larger than 1,000 bytes;
- both PDFs have a PDF header and end marker;
- the EPUB is a ZIP container with the EPUB mimetype and container record;
- the EPUB contains the generated PNG, representative Unicode text, a table and footnote text;
- the DOCX is a ZIP container with content types, the main document, footnotes and embedded media;
- the DOCX main document contains representative Unicode text and a table;
- final status and manifest report a completed four-format build.

These checks prove structural validity, not visual perfection.

## Failure classes

The corpus keeps three outcomes separate.

### Valid or format-specific input

Expected result: `success`.

Markdown accepted by the pipeline must produce all four outputs. Format-specific raw HTML may be omitted by a target format without converting the whole build into invalid input.

### Invalid input

Expected result: `invalid-input`.

The malformed-YAML fixture must fail during Pandoc parsing. The pipeline must:

- return failure;
- record `status=failed` and `step=error`;
- preserve the Pandoc YAML diagnostic in `logs/build.log`;
- preserve the Python failure trace in `logs/error.log`;
- produce no output files.

### Export-tool failure

Expected result: `export-tool-failure`.

A valid manuscript is paired with an injected exporter exception. Its status message must identify the injected tool failure and must not contain the malformed-YAML diagnostic.

This keeps invalid source evidence distinct from an exporter or toolchain failure without changing the accepted production API.

## CI evidence

CI runs the full existing test suite plus the corpus. When the representative build passes, the workflow uploads:

```text
h08-representative-outputs
```

The artifact contains the four outputs, cleaned Markdown, build log, final status, final manifest and a small summary record. It is retained for fourteen days.

## Controlled review

Before H-08 closes, review the uploaded representative outputs for:

- readable opening punctuation and accented words;
- visible image placement;
- readable table structure;
- visible footnote handling;
- nested-list indentation;
- a page transition at the explicit break in both PDFs;
- usable heading hierarchy and table of contents;
- complete long-chapter output without truncation;
- absence of empty or corrupted files.

This review is structural acceptance only. It must not become editorial rewriting, cover design, imposition, bleed, colour or physical-proof approval.
