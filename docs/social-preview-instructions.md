# Social preview image

GitHub shows a "social preview" card when the repository is shared on Slack,
Discord, LinkedIn, X, or in link unfurls. Without one, GitHub renders a generic
grey placeholder.

## Required specification

| Property | Value |
| --- | --- |
| Dimensions | **1280 × 640 px** (2:1) |
| Max file size | 1 MB |
| Format | PNG (preferred) or JPG |
| Theme | Dark background (matches the `docs/index.html` racing theme) |
| Primary text | **Pitwall Agent** |
| Secondary text | Short tagline, e.g. *Deterministic endurance stint planning* |
| Safe area | Keep all text at least 80 px from every edge — link unfurls crop the edges |

Design notes:

- Background: near-black (`#0b0d10`–`#12151a`) with a subtle track/asphalt texture
  or diagonal accent stripe.
- Accent colour: the site's racing accent (warm amber / red) for a thin rule or
  the tagline underline.
- Typography: one bold sans-serif weight for "Pitwall Agent", one lighter weight
  for the tagline. Avoid more than ~8 words total.
- Do **not** include claims that are not true of the alpha (no "AI-powered race
  wins", no lap-time guarantees). Keep it factual.
- Do not use manufacturer logos, real team liveries, or series marks.

## Files in this repository

- `docs/social-preview.svg` — editable source.
- `docs/social-preview.png` — exported raster used for upload.

To re-export the PNG from the SVG after editing:

```bash
# either tool works
rsvg-convert -w 1280 -h 640 docs/social-preview.svg -o docs/social-preview.png
# or
inkscape docs/social-preview.svg -w 1280 -h 640 -o docs/social-preview.png
```

Verify the result:

```bash
python -c "from PIL import Image; im=Image.open('docs/social-preview.png'); print(im.size, im.mode)"
# expected: (1280, 640) RGB or RGBA
```

## Uploading it to GitHub

1. Open **Settings → General** in the repository.
2. Scroll to **Social preview**.
3. Click **Edit → Upload an image…** and choose `docs/social-preview.png`.
4. Confirm the preview thumbnail renders with the text fully visible.

The image is stored by GitHub separately from the repository — committing the PNG
alone does **not** set the preview; the upload step above is required.
