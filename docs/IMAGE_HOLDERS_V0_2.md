# Image holders v0.2 — controlled rendering

Image holders v0.2 extend the v0.1 validation contract into deterministic, writer-aware rendering. The named holder remains the author-facing layout instruction; authors do not receive arbitrary page coordinates, floating controls or freeform geometry.

The v0.1 validation rules remain in force. See `docs/IMAGE_HOLDERS_V0_1.md` for source suitability, aspect-ratio, crop-loss, effective-DPI, caption, decorative and local-file checks.

## Rendering authority

Validated holder images are passed through `filters/image_holder_render.lua` for every production writer. The filter owns holder geometry and therefore replaces or removes author-supplied `width`, `height`, `style` and `latex-placement` values on holder images.

The physical holder widths are maximum intended widths:

| Holder | Rendering width | Block behaviour | Caption behaviour |
|---|---:|---|---|
| `inline` | 5.5 in | stays in source text/block flow | optional; alt text is not promoted to a visible caption unless `caption=` is supplied in a figure context |
| `feature` | 6.25 in | controlled non-floating figure in the PDF templates; ordinary figure semantics elsewhere | required and visibly associated |
| `portrait` | 3.5 in | narrow controlled image/figure | optional; alt text remains accessibility text when no `caption=` is supplied |
| `full-page` | 6.25 in | deterministic page break before and after | required and visibly associated |
| `ornament` | 1 in | decorative separator image | no visible caption; EPUB/HTML receives presentation/hidden accessibility semantics |

A writer may clamp an image below its requested maximum when the document's printable/content box is narrower. It must not enlarge the holder beyond its named maximum.

## Format mapping

### Standard and ND PDF

Pandoc receives the holder width as a physical image width. Both Book System PDF templates already use `graphicx`, bound images to `\textheight`/`\linewidth`, load `float`, and force figure placement to `H`, so feature/portrait/full-page figures do not drift as arbitrary floats.

`full-page` emits `\clearpage` before and after the figure. This means full-page treatment is deterministic within the printable text box; v0.2 does not claim bleed or cover-layout semantics.

### DOCX

Pandoc receives the same physical image widths and maps them into Word drawing extents. Word/Pandoc may clamp a 6.25 in feature/full-page image to the document's available text width. Full-page holders receive explicit OpenXML page breaks before and after.

### EPUB

Pandoc emits holder classes and physical width styles into EPUB XHTML. Feature and portrait figure spacing is controlled with fixed margins and break-inside avoidance where the reader supports it. Full-page holders receive HTML page-break markers before and after. EPUB remains reflowable, so this is a semantic pagination request rather than a claim that every reading system has identical physical pages.

### Shared captions and accessibility

`caption=` is converted into the visible Pandoc figure caption. The Markdown image description remains the image accessibility text. This avoids the default `implicit_figures` behaviour in which alt text can otherwise become the visible caption.

Caption-required holders (`feature`, `full-page`) must be standalone figure-context images. Inline use fails during manuscript input validation with `image-holder-requires-figure-context`.

`ornament` remains `decorative=true`; HTML/EPUB output is additionally marked `role="presentation"` and `aria-hidden="true"`.

## Relative user assets

The cleaned manuscript is built from `work/book-clean.md`, but user-supplied images normally live under the job's `input/` tree. v0.2 passes both the manuscript input directory and cleaned-work directory through Pandoc's resource path so relative holder images resolve without requiring absolute server paths.

## Crop boundary

v0.2 does **not** mutate or destructively crop uploaded raster files. The v0.1 crop-loss rule remains a source-suitability validation boundary: it determines whether the source is close enough to the holder's permitted shape range. Automatic raster cropping would require a separate explicit image-derivation contract, including provenance for generated assets, and is not silently introduced here.

## Compatibility

Images without a holder retain existing Pandoc behaviour. Holder rendering is opt-in through `holder=` or `image-holder=`.

Unknown, blank or conflicting holder declarations still fail during v0.1 validation. The rendering filter also fails closed if unknown/conflicting holder metadata somehow reaches it, providing defence in depth.

## Readiness boundary

Holder-aware rendering does not make an actual manuscript print-ready by itself. BOS-RDY-001 and the established human/artifact acceptance gates remain authoritative for actual-book readiness.
