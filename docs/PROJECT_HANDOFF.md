# Pitwall Agent — Project Handoff

Durable context for any future agent or contributor who picks up this repository
with no memory of previous conversations. Read this file first, then
`AGENTS.md`, then `docs/ARCHITECTURE.md`.

Last updated: 2026-07-26, for the `feat/launch-and-docs` branch targeting
`v0.4.0-alpha.1`.

---

## 1. Product purpose

Pitwall Agent is a **local-first, terminal-based, pre-race endurance strategy
tool**.

Tagline: *Build your endurance race plan, lap by lap — deterministically.*

You give it race duration, lap time, fuel burn, tank size, tyre life, driver
count and driver rules — or a telemetry CSV — and it produces:

- three ranked strategies (Conservative, Balanced, Fuel Save);
- an exact stint plan (laps, driver, fuel start/added, tyre set, pit time);
- P10/P90 uncertainty bounds;
- Evidence Level A/B/C labelling on every input;
- strategy trigger cards (HOLD / RECONSIDER thresholds);
- a Markdown pit sheet and machine-readable JSON.

It is **not**: live timing, live race control, competitor prediction, a
proprietary telemetry integration, or production-validated software.

### The safety principle (non-negotiable)

> **AI may explain the plan, but it must never invent, change, or own the race
> mathematics.**

Every violation of that sentence is a bug, regardless of how useful the feature
looks.

---

## 2. Architecture overview

```
engine/            deterministic race mathematics — no AI, no I/O, pure logic
  models.py        typed dataclasses: RaceConfig, PlanResult, Stint, etc.
  planner.py       stint/fuel/driver plan construction
  strategy.py      Conservative / Balanced / Fuel Save comparison + ranking
  simulation.py    seeded uncertainty model, P10/P90 bounds
  telemetry.py     CSV ingest, column mapping, outliers, evidence calibration
  regulations.py   checks against the driver/stint rules the user configured
  safety_car.py    declared pre-race Safety Car what-if scenario
  trigger_cards.py HOLD / RECONSIDER threshold cards (added in PR #16)

pitwall/           terminal application layer
  cli.py           Typer CLI: doctor, init, welcome, plan, compare, ingest,
                   scenario, export, validate, chat
  tools.py         the allowlisted tool surface the model may call
  agent.py         optional Ollama loop; enforces SYSTEM_POLICY and redaction
  redaction.py     replaces driver names with Driver_1..N before the model sees data
  guided.py        `init --guided` interactive setup with validated ranges
  welcome.py       plain-English concept explanations
  validation_report.py  planned-vs-actual comparison report
  workspace.py     .pitwall/ workspace, non-overwriting report writes
  config.py        race.json load/save
  memory.py        local session history
  presets/         bundled synthetic presets (Evidence Level C)

tests/             pytest suite; CI enforces ruff + 85% coverage
docs/              architecture, strategy/agent brains, landing page, launch material
.github/workflows/ ci.yml, codeql.yml, pages.yml
```

Data flow: `race.json` (+ optional telemetry CSV) → `engine/` → `pitwall/tools.py`
→ CLI rendering or JSON → optional model *explanation only*.

---

## 3. The four personas

Every change should be checked against all four.

| Persona | Who | What they need |
|---|---|---|
| **Arjun** | Complete beginner. Windows. No Python, Git, or racing background. | Install and first plan in 10–20 minutes. Every term explained. No jargon without a definition. `pitwall welcome`, `init --guided`. |
| **Maya** | Sim-racing team captain. | Auditable pit sheets, not black-box advice. Every assumption, confidence level and warning visible before stint 1. |
| **Leo** | Technical contributor. | Typed code, JSON output, tests, CI, documented architecture. Wants to fork and prove the maths. |
| **Race-day operator** | Person on the pit wall during the event. | One scannable page: fuel, tyres, drivers, timing, trigger cards, uncertainty bounds. No scrolling, no ambiguity. |

---

## 4. Safety boundaries

**The model may:** call allowlisted deterministic tools, summarise their output,
explain terminology, and say it does not know.

**The model may never:** compute or alter race numbers, access a shell, browser,
arbitrary files, arbitrary network endpoints, or deletion; see real driver names
(they are anonymised by `pitwall/redaction.py`); claim live-race knowledge;
override a regulation result.

### Seven product anti-patterns — do not ship these

1. A hidden "AI optimum" score that cannot be traced to deterministic code.
2. Any live-race or live-timing claim without a supported, documented feed.
3. Fabricated validation: testimonials, download counts, stars, accuracy claims.
4. Unsourced circuit/tyre multipliers presented as facts.
5. Silent overwriting of a user's reports or race config.
6. Sending user telemetry off the machine, or adding analytics/tracking.
7. False precision — a single number where the honest answer is a P10–P90 range.

---

## 5. Major history

1. **Original prototype** — a Streamlit dashboard stint planner with Plotly and
   pandas.
2. **PR #1 "Reinvent planner as local-first Pitwall Agent"** — full rebuild into
   a terminal application: deterministic `engine/`, Typer CLI, optional Ollama,
   `.pitwall/` workspace, adversarial tests, wheel build in CI. Streamlit,
   Plotly and pandas were removed as runtime dependencies.
3. **PRs #2–#10, #15 — dependency maintenance.** Actions and dev-dependency
   bumps, resolved and merged. `main` HEAD before this work: `e3300c3`.
4. **Audit (2026-07)** — a full repository audit produced a 15-gap analysis
   covering pit-sheet completeness, honesty labelling, onboarding, and missing
   launch/handoff documentation.
5. **PR #16 `agent/audit-usability-hardening`** — Phase B+C audit remediation:
   trigger cards, guided init, `validate`, `welcome`, driver redaction,
   workspace overwrite protection, richer pit sheets, README glossary.
   **Open, not merged at the time of writing.**
6. **This branch `feat/launch-and-docs`** — landing page, Pages workflow, launch
   material, this handoff, `AGENTS.md`, version bump, changelog, README badges.

---

## 6. Current release state

- Last tagged release: **v0.3.0-alpha.1**.
- In progress: **v0.4.0-alpha.1** (`pyproject.toml` version `0.4.0a1`).
- `main` HEAD when this branch was cut: `e3300c3`.
- Two branches in flight: `agent/audit-usability-hardening` (PR #16) and
  `feat/launch-and-docs` (this one). **They were cut independently from `main`.**
  Whichever merges second may need a small merge resolution — most likely in
  `CHANGELOG.md` and `README.md`.
- GitHub Pages: workflow added in this branch. Pages must also be enabled in
  repository settings with source = **GitHub Actions** before the first deploy
  can succeed.

---

## 7. Open issues

| # | Title | Status |
|---|---|---|
| #11 | Publish the first real-session validation case | Open. **Highest-value item in the project.** Blocks the Evidence C → A/B story and the 1.0 gate. |
| #12 | Add one documented simulator telemetry adapter | Open. 0.4 roadmap item. |
| #13 | Generate evidence-backed strategy trigger cards | Open on the tracker, but **implemented in PR #16** (`engine/trigger_cards.py`). Close it when #16 merges. |

---

## 8. Roadmap

**0.4 — real race projects:** guided prompts for event-specific regulations and
service rules; adapters for common simulator CSV formats; measured
predicted-vs-actual validation reports; trigger cards. *(Guided prompts,
validation reports and trigger cards land with PR #16; simulator adapters
remain open as #12.)*

**0.5 — interoperability:** read-only MCP server for the deterministic tools;
optional local HTTP API; versioned import/export schema; scheduled post-session
calibration report.

**1.0 gate:** at least three anonymised real-session case studies; public error
metrics for pace, fuel burn, stop count and classified laps; two championship
rule packs backed by current public sources; external reproduction of install →
ingest → compare → export; stable config and report schemas; documented
migration policy and recovery tests.

**Explicitly not planned:** general shell or browser control; autonomous changes
during a live race; hidden AI optimum scores; live race-control claims without a
supported feed; proprietary timing-feed scraping; unsourced circuit multipliers.

---

## 9. Verification commands

Run all of these before proposing any merge.

```bash
# environment
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# quality gates (must all pass — CI runs the same)
ruff check .
ruff format --check .
pytest --cov --cov-report=term-missing            # coverage must stay >= 85%

# package build
python -m build
pip install --force-reinstall dist/pitwall_agent-*.whl

# CLI smoke test in a throwaway workspace
cd "$(mktemp -d)"
pitwall doctor
pitwall welcome
pitwall init
pitwall compare
pitwall plan
pitwall scenario
pitwall export --name handoff_check
```

Reference results from the last full audit run on `main`: ruff clean, 35 files
formatted, 56 tests passing, 86.80% coverage. Note that `pitwall/cli.py` and
`pitwall/__main__.py` are omitted from coverage in `pyproject.toml`.

Landing page check (no build step — it is a single static file):

```bash
python -m http.server 8080 --directory docs   # then open http://localhost:8080/
```

---

## 10. Release and deployment process

1. Merge the feature PR into `main` after CI is green. **Never force-push
   `main`. Never merge without a human review.**
2. Bump `version` in `pyproject.toml` (PEP 440 form: `0.4.0a1`).
3. Add a dated section to `CHANGELOG.md` under the new version heading.
4. Tag and push: `git tag v0.4.0-alpha.1 && git push origin v0.4.0-alpha.1`.
5. Build artefacts: `python -m build`; attach `dist/*.whl` and `dist/*.tar.gz`
   to the GitHub release.
6. Draft the release notes from `docs/LAUNCH.md` section 4.
7. GitHub Pages deploys automatically from `.github/workflows/pages.yml` on any
   push to `main` that touches `docs/**`. It can also be triggered manually via
   *Actions → Deploy GitHub Pages → Run workflow*.
8. Verify the live site at <https://dabi-init.github.io/endurance-stint-planner/>
   and confirm `/sitemap.xml` and `/robots.txt` resolve.

---

## 11. Known blockers

- **No real-session validation.** Everything published is synthetic (Evidence
  Level C). This is the single biggest credibility gap. See issue #11.
- **No sourced regulation packs.** The tool checks only user-configured rules;
  championship rule packs need current, citable public sources before shipping.
- **GitHub Pages must be enabled manually.** Settings → Pages → Source: GitHub
  Actions. The workflow cannot enable it for you, and the first run fails
  without it.
- **PyPI publication is not set up.** Until it is, the landing page and README
  must keep pointing users at the GitHub releases wheel as a fallback.
- **PR #16 is unmerged**, so `main` does not yet contain trigger cards,
  `welcome`, `init --guided`, or `validate`, even though this branch's
  documentation describes them as part of `0.4.0-alpha.1`. Merge #16 before
  tagging the release.

---

## 12. Codex / future-agent start checklist

Do these ten things at the start of any new conversation on this repository:

1. Read this file, then `AGENTS.md`, then `docs/ARCHITECTURE.md`.
2. `git fetch --all && git status && git log --oneline -10` — know the real HEAD.
3. List open PRs and issues; check whether PR #16 has merged and adjust.
4. Never work directly on `main`; cut a feature branch from up-to-date `main`.
5. Create a virtualenv and `pip install -e ".[dev]"` before touching code.
6. Run the section 9 verification commands **before** editing, to get a baseline.
7. Check any proposed change against the safety principle and the seven
   anti-patterns in section 4.
8. Check the change against all four personas in section 3.
9. Re-run ruff, pytest and the CLI smoke test; update `CHANGELOG.md` and the docs
   in the same PR as the code.
10. Open a PR with a truthful description. Do not merge it yourself, do not force
    push, and never claim validation, accuracy, or adoption that has not happened.
