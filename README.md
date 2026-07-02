<p align="center">
  <img src="assets/endurance-stint-planner-logo.jpg" alt="Endurance Stint Planner" width="640">
</p>

# Endurance Race Stint Planner

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

**Production race strategy tool** for endurance GT and sportscar racing — fuel-limited stints, tyre life, Pro/Silver/Bronze driver regulations, circuit profiles, Safety Car what-if, and pit-wall exports.

Built for race engineers, team managers, and strategists briefing before green flag. Not live timing software.

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

Opens at `http://localhost:8501` with a **complete 6h Endurance plan** (Spa-Francorchamps) — no input required.

---

## Who This Is For

| User | What they get |
|------|----------------|
| **Race engineer** | Instant stint sheet, Gantt timeline, fuel/tyre geometry, exports |
| **Team manager** | Driver compliance pass/fail, Bronze minimum checks, rotation summary |
| **Strategist** | Tyre what-if slider, Safety Car replan comparison, circuit-aware defaults |

The calculation engine is separated from the UI. Invalid inputs return structured **Infeasibility** messages with suggested fixes — the app does not crash on bad data.

---

## Features

| Capability | Status |
|------------|--------|
| Fuel + tyre limited stint planning | ✅ |
| Pro / Silver / Bronze regulations | ✅ |
| Interactive Plotly Gantt timeline | ✅ |
| Driver compliance pass/fail | ✅ |
| Tyre strategy what-if slider | ✅ |
| Safety Car replan + comparison | ✅ |
| Circuit selection (6 GT venues) | ✅ |
| CSV + pit-wall stint sheet export | ✅ |
| Auto-recompute on input change | ✅ |
| Championship presets (4h / 6h / 24h) | ✅ |

---

## UI — Five Tabs

1. **Stint Plan** — metrics, Plotly Gantt, stint table, strategy briefing, CSV/text export
2. **Driver Compliance** — drive-time chart, regulatory bands, ✅/❌ rule table
3. **Tyre Strategy** — live tyre-life slider with recomputed stints
4. **What-If / Safety Car** — SC inputs, original vs re-planned timelines
5. **Methodology** — assumptions, limitations, validation placeholders

### Sidebar

- Preset selector (default: **6h Endurance**)
- Circuit selector (Spa, Le Mans, Portimão, Monza, Nürburgring GP, Fuji)
- Grouped inputs: Race Parameters, Car & Fuel, Tyres, Pit Stops, Drivers, Regulations
- Plan updates automatically when inputs change; **Recompute Plan** forces a refresh

---

## Project Structure

```
endurance-stint-planner/
├── app.py                      # Streamlit UI only
├── engine/
│   ├── models.py               # Driver, RaceConfig, Stint, PlanResult, Infeasibility
│   ├── planner.py              # Pure stint planning logic
│   ├── circuits.py             # Track profiles
│   ├── recommendations.py      # Plan-based strategy briefing
│   ├── regulations.py          # Driver compliance engine
│   └── safety_car.py           # Safety Car re-planning
├── circuits/circuits.json      # Extensible track data
├── presets/                    # 4h, 6h, 24h JSON presets
├── tests/                      # 30+ unit & smoke tests
├── .github/workflows/ci.yml    # Automated test on push
├── .streamlit/config.toml      # Dark theme
├── assets/                     # Project logo
└── requirements.txt
```

---

## Strategy Logic

```
stint_laps = min(fuel_laps, tyre_life_laps, driver_cap_laps)
pit_time   = pit_lane_loss + tyre_change (if enabled)
```

High tyre-wear circuits automatically shorten stint targets. Driver rotation prioritises minimum-drive quotas, then round-robins.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

CI runs automatically on every push to `main` (Python 3.11 and 3.12).

---

## Deploy (Streamlit Community Cloud)

1. Go to [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub
2. **Create app** → Repository: `Dabi-init/endurance-stint-planner`, Branch: `main`, Main file: `app.py`
3. Deploy — auto-redeploys on every push to `main`

---

## Push Updates to GitHub

Copy-paste from your project folder:

```bash
# Check what changed
git status

# Stage all project files
git add app.py engine/ circuits/ presets/ tests/ .streamlit/ requirements.txt requirements-dev.txt README.md assets/

# Commit with a clear message
git commit -m "feat: polish Streamlit app v1.2 — five tabs, auto-recompute, circuit profiles"

# Push to GitHub
git push origin main
```

First-time setup (if cloning fresh):

```bash
git clone https://github.com/Dabi-init/endurance-stint-planner.git
cd endurance-stint-planner
# ... make changes ...
git add .
git commit -m "your message"
git push origin main
```

### Set the repository logo / social preview image

GitHub shows the **first image in README.md** on the repo home page (already set to `assets/endurance-stint-planner-logo.jpg`).

For the **social preview** (link cards on Twitter/LinkedIn/Slack):

1. Open `https://github.com/Dabi-init/endurance-stint-planner/settings`
2. Under **General** → **Social preview** → **Edit**
3. Upload `assets/endurance-stint-planner-logo.jpg` (recommended 1280×640 px)
4. Save

---

## Limitations

- No live timing or real-time race-day feeds
- No traffic, weather, or competitor gap modelling
- Constant fuel consumption; linear tyre life cap
- Safety Car model is strategic what-if, not procedure-accurate

---

## Author

**Sreenath R.** — ESSEC MIM 2026 · [github.com/Dabi-init](https://github.com/Dabi-init)

---

## Licence

MIT — see [LICENSE](LICENSE).