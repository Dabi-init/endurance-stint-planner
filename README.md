<p align="center">
  <img src="assets/endurance-stint-planner-logo.jpg" alt="Endurance Stint Planner" width="640">
</p>

# Endurance Race Stint Planner

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![pandas](https://img.shields.io/badge/pandas-2.0+-150458?style=flat-square&logo=pandas&logoColor=white)](https://pandas.pydata.org/)
[![matplotlib](https://img.shields.io/badge/matplotlib-3.7+-11557c?style=flat-square)](https://matplotlib.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

**Pre-race stint planning tool** for endurance sportscar racing — with series-specific regulations, fuel + tyre limits, gap simulation, and a real-race validation case study.

**Repository:** [github.com/Dabi-init/endurance-stint-planner](https://github.com/Dabi-init/endurance-stint-planner)

---

## What This Tool Does (Honestly)

This is a **pre-race planning and briefing tool**, not live pit-wall software. It helps you:

| Capability | Status |
|------------|--------|
| Fuel-limited stint geometry | ✅ Implemented |
| Tyre degradation + compound selection | ✅ Basic model |
| Series-specific regulations (Fun Cup, ELMS) | ✅ Fun Cup + ELMS rule packs |
| Mandatory Fun Cup refuelling windows | ✅ Enforced in planner |
| Driver balance / Bronze drive quotas | ✅ Validated with errors/warnings |
| Gap / crossover simulation | ✅ Basic static model |
| Safety Car re-plan | ✅ Implemented |
| Real-race validation case study | ✅ Fun Cup Portimão 2024 8h |
| Live timing integration | ❌ Not included |
| FCY vs SC procedure differences | ❌ Not included |
| Multi-car competitor modelling | ❌ Not included |

---

## Quick Start

```bash
git clone https://github.com/Dabi-init/endurance-stint-planner.git
cd endurance-stint-planner
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python endurance_stint_planner.py --preset fun-cup
python endurance_stint_planner.py --self-test
```

---

## New Features

### 1. Series-Specific Regulations

Regulations are loaded per preset from published sporting rules:

| Preset | Regulation pack | Key rules |
|--------|-----------------|-----------|
| `fun-cup` | Fun Cup GT4 (2024 regs) | Mandatory 10-min refuelling windows; driver balance (no driver > 2× others) |
| `elms` | ELMS LMGT3 | Bronze max 65 min/stint, min 45 min/stint, min 2h total drive |
| `wec` | WEC Hypercar (simplified) | Bronze stint caps only — energy/hybrid not modelled |

Regulation breaches print as **ERRORS** (✗). Soft issues print as **warnings** (!).

### 2. Tyre Strategy

Stint length is capped by **both fuel and tyres**:

```
effective_stint = min(fuel_limited, tyre_limited, regulatory_cap, mandatory_window)
```

Compounds: `GTR2` (Fun Cup), `MEDIUM`, `HARD`, `SOFT` (ELMS/WEC).

```bash
# Fun Cup — single mandatory Giti GTR2 compound
python endurance_stint_planner.py --preset fun-cup

# ELMS — alternate compounds per stint
python endurance_stint_planner.py --preset elms --compounds MEDIUM,HARD,MEDIUM,HARD
```

Output includes **Grip End %** (remaining tyre life) and **Limit** column (Fuel-limited / Tyre-limited).

### 3. Gap / Crossover Simulation

Simple static model: compare gap to leader after pitting at different laps.

```bash
python endurance_stint_planner.py --preset fun-cup --gap-sim --gap-to-leader 12 --leader-lap-time 2:06
```

**Limitations:** Assumes constant lap times, no traffic, no SC. Useful for pre-race undercut/overcut sketches only.

### 4. Real-Race Validation Case Study

Compare model output against published stint times from **Fun Cup Portimão 2024 8h, Car #424 (Bollen-Leenders, P2)**.

Source: [Fun Racing Cars pit/stint timing PDF](https://resultscdn.getraceresults.com/2024/Autodromo%20Internacional%20Algarve/FUN%20CUP%20-%20PORTIMAO/FUN%20CUP%20-%20FUN%20CUP%20-%20Course%20%252F%20Race%20-%208h%20-%20Pit%20and%20Stint-times.pdf)

```bash
python endurance_stint_planner.py --validate-case
```

The report shows:
- Assumptions used (fuel, lap time, pit loss, tyre deg)
- Side-by-side actual vs model stint durations
- Mean/max delta — gaps reflect SC, traffic, and repairs the model does not simulate

---

## All Commands

```bash
# Standard 4h Fun Cup plan (fuel + tyre + mandatory windows)
python endurance_stint_planner.py --preset fun-cup

# ELMS 6h with compound rotation
python endurance_stint_planner.py --preset elms --compounds MEDIUM,HARD,MEDIUM

# Gap simulation on first stint
python endurance_stint_planner.py --preset fun-cup --gap-sim --gap-to-leader 15

# Safety Car re-plan
python endurance_stint_planner.py --preset fun-cup --safety-car 125 --extend-stint 8

# Export outputs
python endurance_stint_planner.py --preset fun-cup --export-csv outputs/plan.csv --output outputs/timeline.png

# Real-race validation
python endurance_stint_planner.py --validate-case

# Run all smoke tests
python endurance_stint_planner.py --self-test
```

---

## Championship Presets

| Preset | Series | Duration | Tyre default | Regulations |
|--------|--------|----------|--------------|-------------|
| `fun-cup` | Fun Cup GT4 | 4 hours | GTR2 | Mandatory windows + driver balance |
| `elms` | ELMS LMGT3 | 6 hours | MEDIUM/HARD rotation | FIA Bronze limits |
| `wec` | WEC Hypercar | 6 hours | MEDIUM/HARD | Bronze limits (energy not modelled) |

---

## Strategy Logic

### Stint length

```
usable_fuel = tank - (safety_laps × consumption)
fuel_laps   = floor(usable_fuel / consumption)
tyre_laps   = compound max laps with linear deg (cliff after threshold)
stint_laps  = min(fuel_laps, tyre_laps, laps_to_mandatory_window)
```

### Fun Cup mandatory windows (4h)

| Window | Race minutes |
|--------|-------------|
| 1 | 40 – 50 |
| 2 | 80 – 90 |
| 3 | 120 – 130 |
| 4 | 160 – 170 |
| 5 | 200 – 210 |

*Source: 2024 Fun Cup Sporting Regulations §2.4.4*

### Driver regulations

- **Fun Cup:** Neither driver may exceed 2× combined drive of all others (§2.4.3)
- **ELMS LMGT3:** Bronze max 65 min/stint, min 45 min/stint, min 2h total in 6h race

---

## Project Structure

```
endurance-stint-planner/
├── endurance_stint_planner.py   # Main application
├── requirements.txt
├── README.md
├── docs/                        # Screenshots
└── outputs/                     # Generated files (git-ignored)
```

---

## Current Limitations

Be explicit about what this tool **cannot** do:

- No live timing feed or real-time re-planning during a race
- No FCY vs Safety Car procedure differences
- No multi-car traffic or class-lapped traffic modelling
- No weather, track evolution, or driver-pace delta per stint
- WEC Hypercar energy management is not modelled
- Gap simulation uses static lap times only
- Tyre model is linear degradation — no thermal cycles or compound crossover vs competitors

---

## Future Improvements

Items previously listed that are now **implemented**: tyre degradation, gap simulation, series regulations, real-race validation.

Remaining meaningful next steps:

- Interactive Streamlit dashboard for what-if during briefings
- Timing CSV import to auto-calibrate fuel/lap time from long runs
- FCY vs SC separate pit-loss and procedure models
- Multi-scenario planner (Plan A / SC-early / SC-late branches)
- LMGT3 compound crossover vs competitor stints

---

## Author

**Sreenath R.** — ESSEC MIM 2026

- **GitHub:** [@Dabi-init](https://github.com/Dabi-init)
- **Project:** [endurance-stint-planner](https://github.com/Dabi-init/endurance-stint-planner)

---

## Licence

MIT — see [LICENSE](LICENSE).