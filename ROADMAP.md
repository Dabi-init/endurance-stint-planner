# Roadmap

The roadmap follows race evidence and operator value, not agent feature count.

## 0.3 alpha — local Pitwall Agent

- [x] installable `pitwall` command and interactive terminal;
- [x] editable per-event `race.json` with paste-ready terminal configuration;
- [x] deterministic plan, compare, telemetry, driver-rule, SC, and export tools;
- [x] optional local Ollama function calling;
- [x] no-model fallback and machine-readable JSON;
- [x] workspace file boundary, non-overwriting reports, and local history;
- [x] adversarial agent, model, data, and strategy tests;
- [x] wheel build and clean-install CI.

## 0.4 — real race projects

- [ ] fully guided prompts for event-specific regulations and service rules;
- [ ] adapters for common simulator CSV formats;
- [ ] measured predicted-versus-actual validation reports;
- [ ] trigger cards: burn, pace, tyre, and caution thresholds that change the plan.

## 0.5 — interoperability

- [ ] read-only Model Context Protocol server for the deterministic race tools;
- [ ] optional local HTTP API for team integrations;
- [ ] import/export schema with versioning;
- [ ] scheduled post-session calibration report.

## 1.0 gate

- [ ] at least three anonymised real-session case studies;
- [ ] public error metrics for pace, fuel burn, stop count, and classified laps;
- [ ] two supported championship rule packs backed by current public sources;
- [ ] external user reproduction of install, ingest, compare, and export;
- [ ] stable configuration and report schemas;
- [ ] documented migration policy and recovery tests.

## Explicitly not planned

- general shell or browser control;
- autonomous changes during a live race;
- hidden “AI optimum” scores;
- live race-control claims without a supported feed;
- proprietary timing-feed scraping;
- unsourced circuit multipliers presented as facts.
