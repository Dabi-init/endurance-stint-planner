# Pitwall Agent — Project Handoff

Durable context for any future agent or contributor who picks up this repository
with no memory of previous conversations. Read this file first, then
`AGENTS.md`, then `docs/ARCHITECTURE.md`.

Last updated: 2026-08-02, for the `v0.4.0-alpha.2` hardening release.

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
- result-level Evidence A/B/C, source, confidence, assumptions, and warnings;
- strategy trigger cards (HOLD / RECONSIDER thresholds);
- a Markdown pit sheet and machine-readable JSON.

It is **not**: live timing, live race control, competitor prediction, a
proprietary telemetry integration, or production-validated software.

### The safety principle (non-negotiable)

> **Ollama may route a plain-language request, but it must never invent, change,
> or own the race mathematics.**

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
  agent.py         optional Ollama router; displayed answers are rendered locally
  redaction.py     replaces driver names with Driver_1..N before the model sees data
  guided.py        `init --guided` interactive setup with validated ranges
  welcome.py       plain-English concept explanations
  validation_report.py  planned-vs-actual comparison report
  workspace.py     .pitwall/ workspace, non-overwriting report writes
  config.py        bounded settings TOML parsing and validation
  memory.py        local session history
  presets/         bundled synthetic presets (Evidence Level C)

tests/             pytest suite; CI enforces ruff + 85% coverage
docs/              architecture, strategy/agent brains, landing page, launch material
.github/workflows/ ci.yml and codeql.yml
```

Data flow: a direct command or optional Ollama-routed question → typed
`pitwall/tools.py` call → deterministic `engine/` → local CLI/JSON rendering.
GitHub Pages is hosted separately through the repository's legacy `main:/docs`
branch source; there is no active Pages workflow file.

---

## 3. The four personas

Every change should be checked against all four.

| Persona | Who | What they need |
|---|---|---|
| **Arjun** | Complete beginner. Windows. No Git or racing background. | A source-ZIP launcher, automatic health check, clear setup path, and no jargon without a definition. `pitwall welcome`, `init --guided`. |
| **Maya** | Sim-racing team captain. | Auditable pit sheets, not black-box advice. Every assumption, confidence level and warning visible before stint 1. |
| **Leo** | Technical contributor. | Typed code, JSON output, tests, CI, documented architecture. Wants to fork and prove the maths. |
| **Race-day operator** | Person on the pit wall during the event. | One scannable page: fuel, tyres, drivers, timing, trigger cards, uncertainty bounds. No scrolling, no ambiguity. |

---

## 4. Safety boundaries

**The model may:** propose allowlisted deterministic tool calls using bounded
local context. Pitwall, not model prose, renders every displayed answer.

**The model may never:** compute or alter displayed race numbers, access a shell,
browser, arbitrary files, arbitrary network endpoints, or deletion; claim
live-race knowledge; or override a regulation result. Configured driver names in
tool payloads are anonymised by `pitwall/redaction.py`; users should not put
private identifiers in free-form prompts.

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
5. **Merged PR #16 `agent/audit-usability-hardening`** — Phase B+C audit remediation:
   trigger cards, guided init, `validate`, `welcome`, driver redaction,
   workspace overwrite protection, richer pit sheets, README glossary.
6. **Merged PR #17 `feat/launch-and-docs`** — landing page and staged Pages
   material, this handoff, `AGENTS.md`, version bump, changelog, README badges.
7. **Alpha.2 hardening (PR #19)** — fail-closed configuration
   and race loading, atomic/exclusive writes, bounded storage and provider
   responses, JSON exit-code parity, router-only Ollama grounding, Python 3.14
   CI, and corrected install/onboarding copy.

---

## 6. Current release state

- Current published release: **v0.4.0-alpha.2** (`pyproject.toml` version
  `0.4.0a2`), shipped through GitHub Releases with wheel, source archive, and
  SHA-256 checksums.
- PRs #16, #17, and #19 are merged into `main`.
- GitHub Pages is live at
  <https://dabi-init.github.io/endurance-stint-planner/> and is served from
  legacy source `main:/docs`.

---

## 7. Open issues

| # | Title | Status |
|---|---|---|
| #11 | Publish the first real-session validation case | Open. **Highest-value item in the project.** Blocks the Evidence C → A/B story and the 1.0 gate. |
| #12 | Add one documented simulator telemetry adapter | Open. 0.4 roadmap item. |
| #13 | Generate evidence-backed strategy trigger cards | Open on the tracker although implemented in merged PR #16 (`engine/trigger_cards.py`); tracker cleanup remains. |

---

## 8. Roadmap

**0.4 — real race projects:** guided prompts for event-specific regulations and
service rules; adapters for common simulator CSV formats; a
planned-versus-user-reported comparison generator; trigger cards. *(Guided
prompts, the report generator and trigger cards landed with PR #16; no real
validation result has been published, and simulator adapters remain open as
#12.)*

**Model-discovery UX:** `pitwall model recommend` is an informational,
Ollama-only command that performs an in-memory deterministic core self-check but
never contacts Ollama, downloads a model, creates a workspace, or changes
configuration. It presents core-only/no model as the verified operational path,
`qwen3:8b` (about 5.2 GB) as a provisional first model to try, and `qwen3:4b`
(about 2.5 GB) as a smaller unverified candidate. Every deterministic function
remains available without AI. Keep both model candidates explicitly unverified
until Pitwall publishes a real-model tool-calling conformance benchmark.

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
pitwall race init
pitwall compare
pitwall plan
pitwall scenario 120 20
pitwall export --name handoff_check
```

Record the current test count, coverage, wheel size, and clean-install smoke
results in the pull request; do not carry older audit numbers forward.

Landing page check (no build step — it is a single static file):

```bash
python -m http.server 8080 --directory docs   # then open http://localhost:8080/
```

---

## 10. Release and deployment process

1. Choose `<next-pep440-version>` and `<next-public-tag>`; alpha.2 used
   `0.4.0a2` and `v0.4.0-alpha.2`.
2. Update every runtime/package version reference, then merge the feature PR
   into `main` only after CI and human review. **Never force-push `main`.**
3. Move the `CHANGELOG.md` Unreleased entries under a dated version heading.
4. Build and inspect artefacts with `python -m build`; record their checksums.
5. Tag and push only the reviewed merge commit:
   `git tag <next-public-tag> && git push origin <next-public-tag>`.
6. Create the GitHub release and attach `dist/*.whl`, `dist/*.tar.gz`, and the
   checksum file. Add the versioned asset URL to public install copy only after
   the upload succeeds.
7. Finalise release notes from `docs/LAUNCH.md` section 4.
8. GitHub Pages currently rebuilds from legacy source `main:/docs`; there is no
   active Pages Actions workflow. After merging docs, verify repository Pages
   settings still point there.
9. Verify <https://dabi-init.github.io/endurance-stint-planner/>,
   `/sitemap.xml`, and `/robots.txt` resolve.

---

## 11. Known blockers

- **No real-session validation.** Everything published is synthetic (Evidence
  Level C). This is the single biggest credibility gap. See issue #11.
- **No sourced regulation packs.** The tool checks only user-configured rules;
  championship rule packs need current, citable public sources before shipping.
- **PyPI publication is not set up.** The landing page and README point to the
  versioned GitHub release assets and source ZIP instead.

---

## 12. Codex / future-agent start checklist

Do these ten things at the start of any new conversation on this repository:

1. Read this file, then `AGENTS.md`, then `docs/ARCHITECTURE.md`.
2. `git fetch --all && git status && git log --oneline -10` — know the real HEAD.
3. List open PRs and issues; verify that the handoff still matches repository
   state.
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
