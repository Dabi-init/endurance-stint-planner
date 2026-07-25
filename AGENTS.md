# AGENTS.md

Guidance for AI agents and new contributors working in this repository.
Full context, history and process live in **[docs/PROJECT_HANDOFF.md](docs/PROJECT_HANDOFF.md)**.

Pitwall Agent is a local-first, terminal-based, **pre-race** endurance strategy
tool. Alpha software. All bundled examples use synthetic data (Evidence Level C).

## Repository layout

- `engine/` — deterministic race mathematics (planner, strategy, simulation, telemetry, regulations, safety car, trigger cards). No AI, no network.
- `pitwall/` — terminal app: Typer CLI, allowlisted tools, optional Ollama agent, workspace, redaction, guided setup, validation report.
- `pitwall/presets/` — bundled synthetic race presets (Evidence Level C).
- `tests/` — pytest suite; CI enforces ruff and 85% coverage.
- `docs/` — architecture notes, launch material, project handoff, and the static GitHub Pages site (`docs/index.html`).
- `.github/workflows/` — `ci.yml`, `codeql.yml`, `pages.yml`.
- `examples/`, `assets/` — sample data and brand assets.

## Core commands

```bash
pip install -e ".[dev]"                    # install with dev extras
ruff check . && ruff format --check .      # lint and format gate
pytest --cov --cov-report=term-missing     # tests; coverage must stay >= 85%
python -m build                            # build sdist + wheel
pitwall doctor && pitwall welcome && pitwall init && pitwall compare && pitwall export   # CLI smoke test
python -m http.server 8080 --directory docs                                              # preview the landing page
```

## Product safety boundaries

- **AI may explain the plan; it must never invent, change, or own the race mathematics.** All numbers come from `engine/`.
- The model gets only allowlisted deterministic tools — never shell, browser, deletion, arbitrary files, or arbitrary network access.
- Driver names are anonymised to `Driver_1..N` (`pitwall/redaction.py`) before any tool payload reaches the model.
- Everything is local: no telemetry upload, no analytics, no tracking scripts anywhere — including the landing page.
- Pre-race only. No live timing, no live race control, no competitor prediction. Safety Car support is a declared what-if scenario.

## Release rules

- Version lives in `pyproject.toml` in PEP 440 form (e.g. `0.4.0a1`); tags use `v0.4.0-alpha.1`.
- Every user-visible change needs a `CHANGELOG.md` entry in the same PR.
- CI (ruff, pytest, coverage, wheel build) must be green before merge.
- Releases attach `dist/*.whl` and `dist/*.tar.gz`; release notes come from `docs/LAUNCH.md`.
- GitHub Pages deploys from `docs/` on pushes to `main` via `.github/workflows/pages.yml`.

## Where to find details

- Project history, personas, roadmap, open issues, blockers, verification runs and the start-of-conversation checklist: **`docs/PROJECT_HANDOFF.md`**.
- Engine internals: `docs/ARCHITECTURE.md`, `docs/STRATEGY_BRAIN.md`, `docs/AGENT_BRAIN.md`.
- Roadmap gates: `ROADMAP.md`. Contribution process: `CONTRIBUTING.md`. Reporting: `SECURITY.md`.

## Do NOT

- Do not force-push, or push directly to `main`.
- Do not merge your own PR, or merge with failing/skipped tests.
- Do not fabricate data, testimonials, download counts, stars, accuracy figures, benchmarks, or real-session validation. Say "not validated yet".
- Do not move race maths into a prompt, or let a model output become a displayed number.
- Do not add tracking, analytics, telemetry upload, or any cloud dependency.
- Do not overwrite a user's `race.json` or existing reports; use the workspace's non-overwriting writers.
- Do not present a single number where a P10–P90 range is the honest answer.
- Do not add unsourced circuit, tyre, or fuel multipliers as if they were facts.
- Do not remove evidence levels, disclaimers, or the pre-race-only headers.
