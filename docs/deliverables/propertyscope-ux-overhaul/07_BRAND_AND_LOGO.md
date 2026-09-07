# Brand and logo

## Concept: a bounded view of evidence

The PropertyScope mark combines open framing corners with an irregular parcel-like interior. The frame is a scope: an explicit boundary around the subject under investigation. The stepped shape suggests land/record geometry without depicting an actual title boundary. Open corners keep the mark distinct from a generic house roof or map pin and readable in the header’s small square.

The name remains **PropertyScope NSW**. “NSW” locates the product’s coverage; nothing in the mark imitates a state crest, government seal or official endorsement. The product is independent property research. It must not be presented as a government service or a substitute for professional due diligence.

## Actual production assets

The source assets are in `shared/frontend/design-system/brand/`; identical handoff copies are in this document’s [brand](brand/) folder.

| Asset | Use |
|---|---|
| `propertyscope-logo.svg` | Complete local vector wordmark/lockup |
| `propertyscope-mark.svg` | Compact header/app mark |
| `propertyscope-monochrome.svg` | Single-color use where the full palette is unsuitable |
| `favicon.svg` | Square favicon/app identifier |
| `NOTICE.txt` | Attribution for the glyph-outline source |

The mark is built on a 32-unit grid. Its open-corner path is `M18 4H4v14M14 28h14V14`; the inner parcel path is `M10 10h12v8h-5v5h-7z`. These simple paths scale without raster dependence. The production lockup uses vector glyph outlines, not a remote or embedded font. Header text can remain real system-font text beside the compact mark for accessible responsive layout.

## Usage rules

Use approximately one-quarter of the mark’s width as minimum clear space. Prefer 36px in normal product headers; inspect the compact mark at 20px or smaller before adopting another size. Use the favicon asset for browser chrome rather than shrinking the complete wordmark. Never stretch the frame, rotate the parcel as a status icon or place the full wordmark inside a tiny square.

Use the supplied evergreen on a light neutral surface. Use the monochrome variant when one color is necessary; assess contrast against its actual background. The current product is light-surface first; an untested dark theme is not part of this delivery. Do not add glows, gradients or a government-style enclosure to make it appear more authoritative.

A decorative mark beside real brand text should have empty alt text or be hidden from assistive technology. A standalone logo link needs an accessible name such as “PropertyScope NSW home.” Avoid announcing the same name twice.

## Asset provenance and cost

SVGs are local and contain no external references. The full wordmark’s DejaVu Sans-derived outlines retain their attribution in `NOTICE.txt`; **no font file is bundled**. The interface itself uses system fonts. Four SVGs were parsed for valid XML/viewBox and checked for remote references. No icon package, image CDN or new runtime dependency was added.

## Why it suits both modes

A roof-and-pin identity would overemphasize consumer property listings; a database/robot identity would overemphasize engineering. A bounded parcel/evidence mark can sit above an address search, a source record or a durable AI run without changing meaning. The same geometry is echoed sparingly in entry-page rules and framing, rather than repeated as decoration on every card.
