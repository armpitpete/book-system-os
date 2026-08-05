# Image holders v0.1

Book System OS supports user-supplied local raster images through named image holders. The holder defines the image's role; the template remains responsible for final layout.

## Markdown syntax

```markdown
![A stone bridge](assets/bridge.jpg){holder=feature caption="The eastern bridge after restoration."}
```

Decorative ornament:

```markdown
![](assets/flourish.png){holder=ornament decorative=true}
```

## Built-in holders

| Holder | Ratio range | Target width | Minimum DPI | Crop | Caption |
|---|---:|---:|---:|---|---|
| `inline` | 0.50–2.00 | 5.5 in | 200 | up to 20% | optional |
| `feature` | 1.25–1.90 | 6.25 in | 250 | up to 20% | required |
| `portrait` | 0.55–0.85 | 3.5 in | 250 | up to 15% | optional |
| `full-page` | 0.62–1.55 | 6.25 in | 300 | up to 15% | required |
| `ornament` | 0.25–4.00 | 1 in | 300 | none | prohibited by convention |

## Validation behaviour

Before export, Book System OS checks:

- the local image exists;
- the holder name is recognised;
- JPEG, PNG or WebP content can be decoded safely;
- meaningful images have alt text;
- required captions are present;
- the aspect ratio fits or can be cropped within the holder limit;
- the image has enough pixels for the holder's physical print width;
- ornament images explicitly declare `decorative=true`.

Images without a holder retain the previous compatibility behaviour and are checked only for existence. This allows existing manuscripts to continue working while new publications opt into controlled placement.

## Design boundary

Image holders control geometry and validation. Frames, colour treatments and export-specific rendering remain separate template concerns. Free positioning, arbitrary dimensions, floating text and unsafe SVG uploads are deliberately excluded from v0.1.
