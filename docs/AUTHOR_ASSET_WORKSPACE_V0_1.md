# Author Asset Workspace v0.1

## Purpose

Author Asset Workspace v0.1 closes the author-facing gap between a local image file and Book System OS's existing image-holder validation/rendering contract.

The workspace helps an author answer four bounded questions before the manuscript is queued:

1. **Can Book System OS safely inspect this image?**
2. **Which named holders can this source satisfy?**
3. **What accessibility/caption semantics are required?**
4. **What canonical holder Markdown should be inserted into the manuscript?**

It is not a desktop-publishing canvas and it does not replace the image-holder renderer.

## Author workflow

The authenticated dashboard surface is:

```text
GET /assets
```

The v0.1 flow is:

```text
upload JPEG/PNG/WebP
-> preserve original uploaded bytes in the author-asset store
-> inspect dimensions, format and aspect ratio
-> evaluate all five named holders with the authoritative image-holder validator
-> preview the source image
-> choose a named holder
-> enter alt text / caption / decorative semantics
-> validate that exact semantic selection
-> generate canonical holder Markdown
-> paste the generated Markdown into the manuscript
-> queue the manuscript through the established publishing path
-> copy each referenced workspace asset into the job input tree
-> retain per-job asset identity/provenance
-> existing validator + deterministic renderer consume the copied local asset
```

## Supported input

Uploads are limited to safely decodable raster formats already accepted by the image-holder contract:

- JPEG;
- PNG;
- WebP.

The upload path rejects:

- empty content;
- path-bearing or traversal-style filenames;
- undecodable image data;
- unsupported formats;
- Pillow decompression-bomb conditions;
- images that breach configured storage limits.

Remote-image fetching, data URIs and SVG upload are not part of v0.1.

## Persistent author-asset store

Workspace originals are retained under:

```text
books/assets/<asset-id>/
```

Each asset has a generated 32-character hexadecimal identifier and contains:

```text
source.jpg | source.png | source.webp
metadata.json
```

The metadata record includes:

- asset identifier;
- original filename;
- canonical stored filename;
- canonical manuscript-relative path;
- upload timestamp;
- byte size;
- SHA-256;
- decoded format;
- source pixel width and height;
- aspect ratio.

Runtime asset contents are ignored by Git while `books/assets/.gitkeep` anchors the store. Author uploads must therefore not make the production checkout dirty.

The persistent-state backup includes `books/assets` alongside jobs and Revision Studio, performs secret scanning, rehearses restore, and verifies the restored asset tree byte-for-byte. The protected release wrapper also snapshots the author-asset tree before and after release acceptance and fails if it changes.

## Holder compatibility authority

The workspace does **not** maintain its own independent table of suitability rules.

`app/pipeline/image_holders.py` remains authoritative for:

- permitted holder names;
- aspect-ratio bounds;
- permitted crop-loss bounds;
- physical target width;
- minimum effective DPI;
- caption requirements;
- decorative-only requirements;
- allowed raster formats;
- safe image decoding.

The workspace calls the same `validate_image_holder()` implementation used by the publishing pipeline. A UI compatibility result therefore cannot drift silently from the export-time validator without tests exposing the mismatch.

The five holders remain:

| Holder | Meaning in the author workspace |
|---|---|
| `inline` | Ordinary block/text flow at the controlled inline width |
| `feature` | Standalone feature figure with required visible caption |
| `portrait` | Narrow controlled portrait figure |
| `full-page` | Standalone figure with deterministic page breaks; not bleed or cover layout |
| `ornament` | Decorative separator with presentation-only semantics |

The workspace displays source dimensions, source aspect ratio, effective DPI for each holder, minimum DPI and a direct compatibility/rejection explanation.

## Accessibility and caption semantics

When generating a holder instruction, the author supplies the semantic information required by the existing image-holder contract:

- non-decorative images require alt text;
- `feature` and `full-page` require captions;
- `ornament` requires `decorative=true`;
- decorative images may have empty alt text only where the contract permits it.

These rules are validated before canonical Markdown is returned.

## Canonical Markdown

The workspace returns the same holder syntax already understood by Book System OS. Example:

```markdown
![A stone bridge](assets/0123456789abcdef0123456789abcdef/source.png){holder=feature caption="The eastern bridge after restoration."}
```

Author-supplied alt text and attribute text are escaped before interpolation.

The canonical target is always a controlled workspace path of the form:

```text
assets/<asset-id>/source.<jpg|png|webp>
```

The workspace does not emit arbitrary filesystem paths.

## Job integration

When a manuscript is queued, Book System OS resolves canonical workspace references before creating the persistent job.

For each unique referenced workspace asset it:

1. reloads the author-asset metadata;
2. verifies the retained source SHA-256;
3. includes the referenced asset bytes in job-admission accounting;
4. copies the source into:

```text
books/jobs/<job-id>/input/assets/<asset-id>/source.<ext>
```

5. verifies the SHA-256 of the copied bytes;
6. records inspectable asset provenance in `metadata.json`.

The manuscript target remains relative (`assets/...`), so the existing image-holder validator, renderer and BOS-RDY asset discovery operate on the retained job input rather than on mutable workspace state.

If a referenced workspace asset is missing, corrupt or does not match its recorded identity, job creation fails closed.

## Resource limits

The workspace is not an unmetered upload directory.

At upload, Book System OS checks:

- non-zero bytes;
- the configured per-job storage ceiling as an upper bound for a single source image;
- combined retained job + author-asset storage against `BOOK_MAX_TOTAL_STORAGE_BYTES` (or the runtime default when unset).

At job admission, referenced source-image bytes are added to the job reservation so copying those assets cannot silently bypass the per-job limit.

The production preflight also accounts for combined retained jobs + author assets and verifies the author-asset tree remains unchanged throughout its read-only run.

## Layout boundary

The workspace exposes **semantic holder selection**, not arbitrary geometry.

v0.1 intentionally does not provide:

- x/y coordinates;
- unrestricted image width/height controls;
- free-floating images or text boxes;
- arbitrary text wrapping;
- destructive automatic raster cropping;
- manual crop tooling;
- cover/spine/bleed design;
- printer-specific imposition;
- colour-management controls;
- a general page-layout canvas.

The renderer remains authoritative for deterministic holder geometry across standard PDF, ND PDF, DOCX and EPUB.

## Readiness boundary

A compatible holder means only that the source image and selected semantics satisfy the bounded holder contract.

It does **not** prove that:

- the image is editorially appropriate;
- the page composition is visually accepted;
- a real book is digital-publication-ready;
- a real book is print-ready;
- human artifact inspection has occurred.

BOS-RDY-001 and required exact-artifact human acceptance remain separate gates.

## v0.1 acceptance

The workspace is implementation-accepted only when all of the following pass at the exact reviewed head:

- upload/preview flow;
- all-five-holder compatibility reporting;
- low-resolution rejection sourced from the existing validator;
- alt/caption/decorative validation;
- canonical Markdown escaping;
- path/traversal rejection;
- invalid/unsupported image failure;
- job-input asset copying;
- copied-byte SHA verification;
- per-job asset provenance;
- resource-limit accounting;
- persistent backup/restore coverage;
- release-state preservation coverage;
- preflight author-asset state/capacity coverage;
- existing publishing, security, Revision Studio, image-holder and stable-core tests.

Merge/CI does not deploy the workspace. Production deployment remains a separate exact-SHA authorisation gate, and live human/product acceptance remains separate from machine acceptance.
