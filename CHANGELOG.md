# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
semantic versioning.

## [Unreleased]

Target: `v0.4.0-alpha.2` (not yet tagged or published).

### Added

- a self-healing Windows launcher with a private environment, Python 3.11–3.14
  checks, cache-free installation, dependency/version validation, core-only
  health checks, and first-run interactive onboarding;
- explicit telemetry file, row, and workspace quotas plus bounded local history
  and Ollama responses;
- hostile-input, concurrent-write, JSON error-contract, packaging, and local-AI
  boundary regression coverage;
- a Windows CI launcher smoke and a complete pip source-distribution manifest.

### Changed

- all displayed material race facts now come from deterministic tool results;
  Ollama is an optional local router and is never an arithmetic authority;
- corrupt current-race data fails closed instead of silently switching to demo
  assumptions;
- persistence uses atomic or exclusive writes so interrupted and concurrent
  commands cannot silently overwrite reports or control files;
- install instructions now use working GitHub source/release routes and disclose
  the measured core and optional Ollama disk footprints;
- `doctor` no longer probes Ollama while AI is disabled, and the double-click
  launcher remains usable in deterministic mode when an opted-in model is down.

### Fixed

- machine-readable failures now return nonzero status with valid JSON;
- malformed, non-finite, deeply nested, oversized, or replaced local inputs fail
  safely without a traceback;
- synthetic telemetry remains Evidence Level C after renaming or line-ending
  conversion, while one real imported session can claim Level B at most.

## [0.4.0-alpha.1] - 2026-07-26

Usability, honesty, and launch release. Feature work lands via
[PR #16](https://github.com/Dabi-init/endurance-stint-planner/pull/16)
(Phase B+C audit remediation) plus this documentation and packaging branch.

### Added

- `pitwall welcome`: plain-English explanations of stints, fuel reserve, tyre
  life, P10/P90, evidence levels, pit service, Safety Car scope, trigger cards,
  the deterministic engine, and telemetry (PR #16);
- `pitwall init --guided`: interactive setup with validated ranges, units, help
  text, cross-checks for impossible combinations, and per-field input origin
  (PR #16);
- `pitwall validate`: planned-versus-actual comparison report with provenance
  disclaimers, written to the workspace (PR #16);
- deterministic strategy trigger cards (fuel burn, pace, tyre life, Safety Car
  window) with HOLD/RECONSIDER status, surfaced in plan, comparison, CLI, JSON,
  and the pit sheet (PR #16);
- driver-name redaction to `Driver_1..N` in every tool payload the model sees
  (PR #16);
- workspace non-overwrite protection for report and validation files (PR #16);
- README glossary of core endurance and Pitwall terms (PR #16);
- public GitHub Pages landing page in `docs/` with full SEO metadata,
  `sitemap.xml`, `robots.txt`, and branch-based setup guidance;
- `docs/LAUNCH.md` launch material and `docs/PROJECT_HANDOFF.md` handoff;
- root `AGENTS.md` guidance for future agents and contributors.

### Changed

- `pitwall export` now defaults to the recommended strategy;
- pit sheets label P10 as pessimistic and P90 as optimistic, state the plain
  English meaning of the evidence level, and report the input source (PR #16);
- pit sheets and stint tables include tyre age at stint end and pit duration
  (PR #16);
- plan, comparison, scenario, and chat output carry an explicit pre-race-only
  header, and Safety Car output carries its own disclaimer (PR #16);
- README documents the new commands and links the docs site.

### Known limitations

- alpha software, not production-validated;
- all bundled examples use synthetic data (Evidence Level C);
- no real-session validation case study yet (issue #11);
- no live timing, competitor prediction, or official regulation database.

## [0.3.0-alpha.1] - 2026-07-25

### Added

- installable `pitwall` terminal command and interactive session;
- deterministic no-model question routing;
- optional loopback-only Ollama chat and tool calling;
- typed allowlist for planning, comparison, telemetry, regulations, Safety Car,
  and non-overwriting report export;
- visible `.pitwall` workspace with local history and machine-readable JSON;
- editable current-race configuration for event, car, service, and drivers;
- model misuse, prompt-injection, path-boundary, loop-limit, and overwrite tests;
- package build and wheel-install CI.

### Changed

- reinvented the prototype as Pitwall Agent rather than a Streamlit dashboard;
- separated the optional language layer from all race arithmetic;
- rebuilt the model around exact fuel additions, service timing, tyre sets,
  stable driver identities, uncertainty, and evidence levels;
- replaced the browser launch with paste-ready PowerShell and a terminal doctor.

### Removed

- Streamlit, Plotly, and pandas runtime dependencies;
- unsourced circuit adjustment heuristics;
- placeholder validation and contact claims;
- duplicated application architecture and stale screenshots.

## [1.2.0] - 2026-07-03

- Original deterministic stint-planner prototype.
