# Image holders v0.1

Book System OS supports user-supplied local raster images through named image holders. A holder defines the image's intended role and validates whether the supplied source can safely satisfy that role. The export template remains responsible for final layout.

## Markdown syntax

```markdown
![A stone bridge](assets/bridge.jpg){holder=feature caption="The eastern bridge after restoration."}
```

Decorative ornament:

```markdown
![](assets/flourish.png){holder=ornament decorative=true}
```

`image-holder=` is accepted as an alias for `holder=`.

## Built-in holders

| Holder | Ratio range | Target width | Minimum DPI | Crop | Caption |
|---|---:|---:|---:|---|---|
| `inline` | 0.50–2.00 | 5.5 in | 200 | up to 20% | optional |
| `feature` | 1.25–1.90 | 6.25 in | 250 | up to 20% | required |
| `portrait` | 0.55–0.85 | 3.5 in | 250 | up to 15% | optional |
| `full-page` | 0.62–1.55 | 6.25 in | 300 | up to 15% | required |
| `ornament` | 0.25–4.00 | 1 in | 300 | none | not required |

## Validation behaviour

Before export, Book System OS checks holder-declared images for:

- an existing, inspectable local file;
- a recognised holder name;
- decodable JPEG, PNG or WebP content;
- decompression-bomb limits;
- alt text for non-decorative images;
- required captions;
- an aspect ratio that fits directly or stays within the holder's crop-loss limit;
- enough source pixels for the holder's physical print width and minimum DPI;
- `decorative=true` when the `ornament` holder is used.

Images without a holder retain the previous compatibility behaviour and are checked only for existence when they resolve locally. Existing manuscripts therefore do not become invalid merely because image-holder validation exists.

HTTP(S), data-URI and other non-local targets remain untouched when no holder is declared. An image that opts into a holder must resolve to a local file; otherwise validation fails with `image-holder-requires-local-file`, because BOS cannot honestly prove its dimensions, format or print suitability.

## Readiness binding

Holder syntax uses the same Pandoc image discovery path already consumed by BOS-RDY-001. The compatibility helper `_image_target()` remains available, so adding holder attributes does not make a referenced asset invisible to readiness hashing. A changed external-local image therefore changes the BOS-RDY asset identity even when that image uses a holder.

## Design boundary

Image holders v0.1 are a controlled authoring and validation contract. They do **not** yet introduce free positioning, arbitrary dimensions, floating text, automatic layout/cropping, cover design, image sourcing or SVG upload. Export-specific frames, treatments and final placement remain template concerns.
