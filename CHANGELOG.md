# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
semantic versioning.

## [Unreleased]

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
