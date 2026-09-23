# Publication Model v0.1

## Status

**PHASE 1 FINAL CANDIDATE — ACCEPTANCE EVIDENCE PENDING**

Publication Model v0.1 is the first renderer-independent publication contract in Book System OS.

It does not replace Current Product Contract v1, does not change the production four-output engine, and does not deploy anything.

## 1. Authority boundary

Book System OS is authoritative for:

- canonical publication content;
- publication metadata;
- ordered semantic structure;
- asset identity and semantics;
- publication intent;
- physical-feasibility decisions;
- provenance and validation.

Affinity is the intended future authority for:

- graphical page composition;
- exact frame geometry;
- implemented typography;
- final layout;
- print/export settings;
- final PDF/EPUB or other accepted export operations.

Publication Model v0.1 contains no Affinity document IDs, page coordinates, frame coordinates or renderer commands.

Pandoc, Lua filters and XeLaTeX remain transitional Current Product Contract v1 implementation only. They are not dependencies of this model.

## 2. Top-level model

The schema identifier is:

`publication-model/v0.1`

The generic top-level object is `Publication`.

The only supported publication profile in v0.1 is:

`BookPublication`

Future publication families must extend the generic publication contract rather than changing Book semantics in place.

## 3. Publication metadata

Required metadata:

- stable publication ID;
- title;
- one or more creators;
- language.

Optional metadata:

- subtitle;
- publication/status marker;
- typed external identifiers.

Metadata is separate from content Markdown.

Embedded YAML front matter is not canonical Book System Markdown v0.1 content.

## 4. Content units

Content is an ordered tuple of explicit semantic units.

Supported roles:

- title page;
- copyright;
- dedication;
- epigraph;
- contents;
- preface;
- introduction;
- part;
- chapter;
- section;
- notes;
- bibliography;
- appendix;
- acknowledgements;
- about-author;
- intentional blank page.

Each unit declares:

- stable ID;
- semantic role;
- front/body/back matter;
- optional title;
- optional parent;
- canonical Markdown;
- source provenance;
- referenced asset IDs.

Front matter must precede body matter, and body matter must precede back matter.

A section must have a previously declared chapter or section parent.

A chapter may be nested under a previously declared part.

The model does not infer front/body/back matter from heading text.

## 5. Canonical Markdown v0.1

Content-unit Markdown is UTF-8 text normalized deterministically to LF line endings with one final newline when non-empty.

Supported semantics include:

- ATX headings using one to six `#` characters;
- paragraphs;
- emphasis and strong text;
- block quotes;
- ordered and unordered lists;
- ordinary links;
- footnotes;
- semantic image references;
- scene breaks;
- explicit page-break intent.

Semantic image references use:

`![alt text](asset:<stable-id>)`

The image filename is not the semantic identity.

Caption and accessibility text belong to the Asset object.

Explicit page-break intent uses:

`<!-- bos:page-break -->`

The following are outside v0.1 and fail validation:

- embedded YAML metadata;
- raw HTML;
- fenced code blocks;
- Markdown tables;
- Setext headings;
- image paths that bypass the Asset model.

This contract is deliberately narrower than Pandoc Markdown.

## 6. Assets

Every asset has a stable ID and declares:

- source path;
- media type;
- optional intrinsic pixel dimensions;
- optional alt text;
- optional caption;
- semantic placement intent.

Placement intent values are:

- inline;
- block;
- full page;
- cover.

When an asset root is supplied, the validator confirms that each asset path stays inside that root and that the file exists.

A content-unit asset reference must resolve to a declared Asset.

## 7. Publication intent

Publication intent records design requirements without encoding compositor implementation.

It includes:

- trim size;
- optional custom width and height;
- portrait or landscape orientation;
- binding intent;
- single-page or facing-page intent;
- bleed;
- print/digital/both target;
- monochrome/grayscale/colour intent;
- optional fixed page count;
- broad typography intent;
- semantic style roles;
- chapter-start rule.

Supported named trim sizes are A7, A6, A5 and A4.

Custom trim requires both width and height.

No exact text-frame or page-object geometry exists in this layer.

## 8. Physical feasibility

Feasibility runs before any future Affinity construction.

The result is one of:

- PASS;
- CAUTION;
- REJECT.

The first implementation uses conservative deterministic page-capacity estimates by trim size.

It accounts for:

- word count;
- declared fixed page count;
- explicit page breaks;
- fixed front/back pages;
- intentional blank pages;
- full-page assets;
- recto chapter-start allowance;
- saddle-stitch signature divisibility.

A fixed saddle-stitched publication must have a page count divisible by four.

A publication whose minimum plausible page requirement exceeds the fixed page budget is REJECT.

The permanent hostile case is:

- A7;
- 16 fixed pages;
- 90,000 words.

That case must return `fixed-page-capacity-exceeded` and REJECT.

Feasibility is a production gate, not an aesthetic judgement.

## 9. Validation order

The intended Phase 1 validation sequence is:

1. metadata/schema validation;
2. content-unit structure validation;
3. Markdown contract validation;
4. asset-reference validation;
5. bounded asset-file validation when an asset root is supplied;
6. publication-intent validation;
7. physical-feasibility assessment;
8. deterministic canonical serialization.

Renderer execution is outside this sequence.

## 10. Provenance

Every content unit preserves:

- source path;
- SHA-256 of supplied source text;
- SHA-256 of canonicalized Markdown;
- optional source line range.

The publication itself has deterministic canonical JSON and a canonical SHA-256 identity.

Canonical JSON uses stable key ordering and deterministic separators.

The same accepted inputs therefore produce the same publication identity.

## 11. Compatibility

Current Product Contract v1 remains unchanged.

Its accepted output keys remain:

- `pdf_standard`;
- `pdf_nd`;
- `epub`;
- `docx`.

Phase 1 does not silently reinterpret current-engine manuscripts as Publication Model v0.1.

Existing manuscripts remain governed by their existing contract until an explicit migration/import contract is accepted.

The Phase 1 representative corpus exercises current prose, front matter, back matter, images, footnotes and nested structural cases without changing the legacy engine.

## 12. Representative corpus

The Phase 1 fixture corpus contains:

- minimal one-chapter book;
- normal multi-chapter book;
- front matter;
- back matter;
- images;
- notes;
- nested sections;
- short A7 chapbook;
- fixed-page publication;
- impossible A7/90,000-word publication;
- missing asset reference;
- malformed metadata;
- invalid content ordering.

The corpus lives at:

`tests/fixtures/publication_model/cases.json`

## 13. Affinity handoff contract

A future Affinity bridge may consume only accepted Publication Model data.

It receives:

- canonical ordered content units;
- semantic roles and hierarchy;
- publication metadata;
- asset identities and metadata;
- publication intent;
- feasibility result;
- provenance identities.

Book System OS has already decided what the publication means.

The Affinity bridge decides how those semantics are realized in an Affinity document.

The bridge must not require canonical Markdown to contain inverted text, imposed sheet order, frame coordinates or other printer/compositor-specific mutations.

A7-on-A4 imposition is therefore downstream production work.

## 14. Excluded dependencies

The `app/publication/` package must not import or invoke:

- Pandoc;
- Lua;
- XeLaTeX;
- PDF generators;
- EPUB generators;
- Affinity APIs.

Those belong either to the transitional current engine or to later compositor/export phases.

## 15. Acceptance requirements

Publication Model v0.1 is accepted only when:

- the Phase 1 test suite passes;
- the full repository regression passes in supported CI;
- the fixture corpus passes;
- the A7/90,000 hostile case rejects;
- deterministic round-trip serialization passes;
- asset path escape and missing-file tests pass;
- current four-output authority remains unchanged;
- no renderer dependency enters `app/publication/`;
- `git diff --check` passes;
- changed paths remain bounded;
- hostile architectural review passes;
- exact-head CI evidence passes;
- work stops before protected-main merge.

## 16. Definition of done

Phase 1 is complete when Book System OS can transform explicit Markdown content units, metadata, assets and publication intent into a validated deterministic Book Publication model that is safe to hand to a future Affinity bridge.

Phase 1 does not typeset, export or deploy the book.
