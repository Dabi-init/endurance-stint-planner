# Product screenshot showcase design

## Goal

Show prospective users what Pitwall Agent actually does, using screenshots of
the released terminal application rather than mockups or invented results.

## Screenshots

Two PNGs will be captured from a fresh local workspace using the bundled
synthetic 6-hour endurance preset:

1. `docs/assets/pitwall-compare-demo.png` — the ranked Conservative, Balanced,
   and Fuel Save comparison.
2. `docs/assets/pitwall-plan-demo.png` — the stint-by-stint deterministic plan
   and its trigger cards.

Each image will use a readable terminal size and be accompanied by the exact
caption: "Synthetic example data (Evidence Level C) — not a performance
claim."

## Placement

- The README gains a compact "See it working" section directly after the
  introductory explanation, with both screenshots and their captions.
- `docs/index.html` replaces the text-only terminal illustration with the
  comparison screenshot and a link to the plan screenshot. Existing alpha,
  safety, local-first, and Ollama-only boundaries remain visible.
- Images live under `docs/assets/` so the repository and GitHub Pages use one
  version of each file.

## Accuracy and accessibility

- Captures come from the installed `v0.4.0a2` package, not a mock terminal.
- The setup uses no Ollama model and makes no network call.
- Images use descriptive alt text; the surrounding captions preserve the
  Evidence Level C disclaimer for users who cannot see the screenshots.
- The landing-page layout remains responsive at desktop and mobile widths.

## Verification

Before publishing, verify that the screenshots match fresh command output,
that README image paths render on GitHub, that the landing page references the
same files, and that the automated test/lint checks remain green. The change
will be submitted through a pull request; `main` will not be modified directly.
