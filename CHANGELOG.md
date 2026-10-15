# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
semantic versioning.

## [Unreleased]

### Added

- a local API (`python -m pitwall_api`, optional `api` extra) that creates a
  plan, compares scenarios, and re-plans a safety car for the endurance engine
  and a new F1 planner;
- versioned F1 season and event files for tyre compounds, mandatory compound
  use, pit-lane loss, and no refuelling, with user overrides and an optional
  entry-list refresh from OpenF1 and Jolpica before an event;
- driver and team cards that carry a headshot URL, a team colour, and an
  optional livery URL, stored as links only (image files are not downloaded);
- an offline back-test (`python -m backtest`) of the 2024 Bahrain Grand Prix,
  car 1, reporting predicted stints and race time against the recorded result.
  This is one comparison under file assumptions, not a validation claim;
- a local pit-wall page at `/` when the API is running: dark timing tower,
  strategy timeline, scenario cards, a replay of the 2024 Bahrain Grand Prix,
  and plain-language explanations. Headshots are OpenF1 links, not stored files;
- a pluggable lap feed. The free source replays the bundled Bahrain recording
  and can declare a safety-car or virtual-safety-car what-if. OpenF1's paid
  live socket stays closed unless a server transport is plugged in, and a
  server token is never returned to the browser;
- an undercut sum from a gap, a number of laps, and a tyre-gain assumption you
  type in, plus a seeded sample of one plan's degradation and pit-lane loss.
  That sample is labelled as not a historical P10–P90 forecast;
- an endurance view on the same pit wall for the bundled synthetic presets,
  with Pro, Silver, and Bronze drive time, separate class plans, a safety-car
  window you type in, and a lap-row preview. A pasted timing URL is refused.
  Pitwall does not fetch or redistribute Al Kamel timing.

### Fixed

- the F1 fuel check rejects a starting load above the tank before it compares
  fuel used with the fuel on board;
- a dry race searches slick compounds only, so Intermediate and Wet cannot
  lift the two-compound rule. A wet race can still use a wet-weather tyre;
- a pasted timing link is refused with the words "does not fetch a pasted URL";
- a safety-car re-plan can add a declared field lap-time loss and rival pit
  stops (both default to zero, so a pit-only window is unchanged);
- an endurance safety car whose deploy minute sits outside the race returns
  422 instead of being clamped. A negative deploy minute says it must be zero
  or higher;
- an F1 event round outside 1–30 returns 422 on the event and prepare routes;
- the pit-wall docs say the Bahrain replay is opened with POST, and GET on
  that path returns 405;
- a malformed back-test fixture prints a readable error instead of a bare
  `KeyError`;
- plan requests bound stint length, compound name length, season, round, and
  the number of scenarios;
- the timing tower escapes grid and finish position before writing HTML, the
  replay scrub stays hidden outside replay mode, a deep-linked lap is clamped
  into the race, and a bad replay override returns 422. The replay is opened
  with POST only;
- the pit wall script is split into a format module, an F1 view, and an
  endurance view. Classes are described as separate plans with no traffic,
  passing, or shared pit lane, and a preset name cannot leave the bundled
  directory;
- the undercut sum includes an out-lap warm-up, an in-lap delta, and traffic
  avoided (all default to zero). A negative gap or pit loss is rejected, a
  reversed or negative safety-car window returns 422, a live deep link is
  clamped into the race, and the lap stream waits with async sleep. The sample
  on the page is labelled a race-time spread.

## [0.4.0-alpha.2] - 2026-08-02

### Added

- a self-healing Windows launcher with a private environment, Python 3.11–3.14
  checks, cache-free installation, dependency/version validation, core-only
  health checks, and first-run interactive onboarding;
- explicit telemetry file, row, and workspace quotas plus bounded local history
  and Ollama responses;
- hostile-input, concurrent-write, JSON error-contract, packaging, and local-AI
  boundary regression coverage;
- a Windows CI launcher smoke and a complete pip source-distribution manifest;
- `pitwall model recommend`, a read-only core self-check that presents an
  Ollama-only 8B first-try candidate, a smaller unverified 4B candidate, and the
  verified zero-model-storage path without downloads or configuration changes.

### Changed

- all displayed material race facts now come from deterministic tool results;
  Ollama is an optional local router and is never an arithmetic authority;
- corrupt current-race data fails closed instead of silently switching to demo
  assumptions;
- persistence uses atomic or exclusive writes so interrupted and concurrent
  commands cannot silently overwrite reports or control files;
- install instructions now use working GitHub source/release routes and disclose
  the measured core and optional Ollama disk footprints; Windows examples use
  the application-policy-friendly `python -m pitwall` entry path;
- `doctor` no longer probes Ollama while AI is disabled, and the double-click
  launcher remains usable in deterministic mode when an opted-in model is down;
- the Ollama HTTP client now ignores environment proxies and rejects redirects,
  keeping prompts and tool context on the validated loopback endpoint.

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
