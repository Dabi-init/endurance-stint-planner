# Product Screenshot Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Add accurate, accessible screenshots of Pitwall's released terminal workflow to the README and public GitHub Pages site.

**Architecture:** Capture two fixed terminal views from the installed \`0.4.0a2\` package in a fresh synthetic workspace. Store the screenshots once under \`docs/assets/\`, then reference the same files from README and \`docs/index.html\` with Evidence Level C captions.

**Tech Stack:** Python 3.14, Pitwall Agent CLI, Windows terminal capture, Markdown, static HTML/CSS, GitHub Pages.

## Global Constraints

- Capture only the bundled synthetic 6-hour preset; never present a screenshot as real-session data.
- Caption each image exactly: "Synthetic example data (Evidence Level C) — not a performance claim."
- Run in core-only mode: do not install, contact, or download an Ollama model.
- Keep image files in \`docs/assets/\` so GitHub and GitHub Pages share one source.
- Keep all existing alpha, pre-race-only, local-first, and Ollama-only boundaries intact.
- Submit via a pull request; never push directly to protected \`main\`.

---

### Task 1: Capture released CLI evidence

**Files:**
- Create: \`docs/assets/pitwall-compare-demo.png\`
- Create: \`docs/assets/pitwall-plan-demo.png\`
- Test: fresh CLI commands from the installed \`0.4.0a2\` wheel

**Interfaces:**
- Consumes: \`pitwall\` CLI with \`--home <fresh-workspace>\`, \`race init\`, \`compare\`, and \`plan\`.
- Produces: two readable PNG captures containing only bundled synthetic inputs and deterministic output.

- [ ] Install the released wheel in an isolated test environment and assert \`pitwall.__version__ == "0.4.0a2"\`.
- [ ] Create a new \`.screenshot-demo\` workspace, run \`init\`, \`race init\`, \`compare\`, and \`plan\`.
- [ ] Capture the visible terminal output for \`compare\` and \`plan\` separately; retain the Evidence C and pre-race disclaimers.
- [ ] Open the PNGs and confirm text remains legible at the native size.
- [ ] Commit: \`docs: add authentic terminal screenshots\`.

### Task 2: Add a responsive landing-page showcase

**Files:**
- Modify: \`docs/index.html\`
- Modify: \`tests/test_readme_flow.py\`

**Interfaces:**
- Consumes: \`assets/pitwall-compare-demo.png\` and \`assets/pitwall-plan-demo.png\` relative to \`docs/index.html\`.
- Produces: an accessible \`#demo\` screenshot card, responsive image styling, and a direct plan-image link.

- [ ] Add a focused test requiring both screenshot paths and the exact Evidence Level C caption.
- [ ] Run the focused test and confirm it fails before the page change.
- [ ] Add a \`.terminal-shot\` responsive image style and replace the text-only terminal illustration with the authentic comparison image, caption, and plan-image link.
- [ ] Run the focused test and inspect desktop/mobile views for overflow and caption visibility.
- [ ] Commit: \`docs: show authentic terminal workflow on landing page\`.

### Task 3: Add the GitHub README showcase

**Files:**
- Modify: \`README.md\`
- Modify: \`tests/test_readme_flow.py\`

**Interfaces:**
- Consumes: repository-relative \`docs/assets/pitwall-compare-demo.png\` and \`docs/assets/pitwall-plan-demo.png\`.
- Produces: a concise \`## See it working\` section with two images, descriptive alt text, and the exact synthetic-demo caption.

- [ ] Extend the focused test for README paths and captions; verify it fails before the README edit.
- [ ] Add the compact README section after the local-first/Ollama boundary without analytics, external hosting, or performance claims.
- [ ] Run the focused test and \`git diff --check\`.
- [ ] Commit: \`docs: add terminal workflow screenshots to readme\`.

### Task 4: Run full verification and submit safely

**Files:**
- Verify: \`README.md\`, \`docs/index.html\`, \`docs/assets/pitwall-compare-demo.png\`, \`docs/assets/pitwall-plan-demo.png\`, and \`tests/test_readme_flow.py\`

**Interfaces:**
- Consumes: completed image and document changes.
- Produces: full quality-gate evidence and an open PR against \`main\`.

- [ ] Run \`ruff check .\`, \`ruff format --check .\`, \`python -m compileall -q engine pitwall tests\`, and \`pytest --cov --cov-report=term-missing\`.
- [ ] Confirm the diff contains only screenshots, documentation, and the focused test.
- [ ] Push a feature branch, open a PR to \`main\`, and verify CI, CodeQL, and Pages before merging.

