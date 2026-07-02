<p align="center">
  <img src="assets/endurance-stint-planner-logo.jpg" alt="Endurance Stint Planner" width="640">
</p>

# Endurance Race Stint Planner

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

**Professional race strategy tool** for endurance sportscar racing — fuel-limited stints, tyre life, GT-style driver regulations, Safety Car what-if, and pit-wall exports.

Built for race engineers briefing before green flag. Not live timing software.

**Repository:** [github.com/Dabi-init/endurance-stint-planner](https://github.com/Dabi-init/endurance-stint-planner)

---

## Quick Start

```bash
git clone https://github.com/Dabi-init/endurance-stint-planner.git
cd endurance-stint-planner
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
streamlit run app.py
```

The app opens with the **6h Endurance** preset loaded and a complete stint plan — no input required.

---

## Deploy live (Streamlit Community Cloud)

Get a public URL in ~2 minutes — free, no server setup.

1. Open **[share.streamlit.io](https://share.streamlit.io)** and sign in with **GitHub** (`Dabi-init`).
2. Click **Create app** (top right).
3. Fill in exactly:
   - **Repository:** `Dabi-init/endurance-stint-planner`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Deploy**.

Your app will be live at a URL like:

`https://endurance-stint-planner-dabi-init.streamlit.app`

(Exact subdomain may vary — Streamlit assigns it on first deploy.)

After deploy, every `git push` to `main` auto-redeploys the app.

---

## Features

| Capability | Status |
|------------|--------|
| Fuel-limited stint geometry | ✅ |
| Tyre life cap per stint | ✅ |
| Pro / Silver / Bronze driver regulations | ✅ |
| Interactive Plotly stint timeline | ✅ |
| Driver compliance pass/fail table | ✅ |
| Tyre strategy what-if slider | ✅ |
| Safety Car re-plan comparison | ✅ |
| CSV + pit-wall stint sheet export | ✅ |
| Championship presets (4h / 6h / 24h) | ✅ |
| Structured infeasibility reasons (no crashes) | ✅ |

---

## UI Overview

### Sidebar
- **Preset selector** — 6h Endurance (default), 24h GT3 Endurance, 4h Sprint Endurance
- Grouped inputs: Race Parameters, Car & Fuel, Tyres, Pit Stops, Drivers, Regulations
- **Compute Plan** button (auto-computes on preset change)

### Main Tabs
1. **Stint Plan** — metrics, Gantt timeline, stint table, CSV/text export
2. **Driver Compliance** — drive-time chart with regulatory bands, ✅/❌ rule table
3. **Tyre Strategy** — live tyre-life slider with recomputed stints
4. **What-If / Safety Car** — SC window inputs, original vs re-planned timelines
5. **Methodology** — assumptions, limitations, validation placeholders

---

## Project Structure

```
endurance-stint-planner/
├── app.py                      # Streamlit UI only
├── engine/
│   ├── models.py               # Driver, RaceConfig, Stint, PlanResult, Infeasibility
│   ├── planner.py              # Pure stint planning logic
│   ├── regulations.py          # Driver regulation compliance engine
│   └── safety_car.py           # Safety Car re-planning + comparison
├── presets/
│   ├── 6h_endurance.json
│   ├── 24h_gt3_endurance.json
│   └── 4h_sprint_endurance.json
├── tests/
│   └── test_planner.py
├── .streamlit/config.toml      # Dark theme
├── requirements.txt
└── endurance_stint_planner.py  # Legacy CLI (reference)
```

---

## Strategy Logic

```
stint_laps = min(fuel_laps, tyre_life_laps, laps_for_driver_cap)
pit_time   = pit_lane_loss + (tyre_change if enabled)
```

Driver rotation prioritises drivers below minimum drive quotas, then rotates. Regulation compliance is validated after planning.

---

## Presets

| Preset | Duration | Drivers | Notes |
|--------|----------|---------|-------|
| 6h Endurance | 6 hours | 3 (Pro/Silver/Bronze) | Default — ELMS-style Bronze 2h minimum |
| 24h GT3 Endurance | 24 hours | 4 | Max drive cap per driver |
| 4h Sprint Endurance | 4 hours | 2 | Pro + Silver sprint format |

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Covers fuel/tyre limiting, driver regulations, infeasibility handling, Safety Car replan, edge cases, and preset loading.

---

## Legacy CLI

The original command-line planner remains available:

```bash
python endurance_stint_planner.py --preset fun-cup
python endurance_stint_planner.py --validate-case
```

---

## Limitations

- No live timing feed or real-time race-day re-planning
- No traffic, weather, or competitor gap modelling
- Constant fuel consumption and linear tyre life
- Safety Car model is strategic what-if, not procedure-accurate FCY/SC

---

## Author

**Sreenath R.** — ESSEC MIM 2026

- **GitHub:** [@Dabi-init](https://github.com/Dabi-init)
- **Project:** [endurance-stint-planner](https://github.com/Dabi-init/endurance-stint-planner)

---

## Licence

MIT — see [LICENSE](LICENSE).