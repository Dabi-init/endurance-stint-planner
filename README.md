# Endurance Race Stint Planner

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-2.0+-150458?style=flat-square&logo=pandas&logoColor=white)
![matplotlib](https://img.shields.io/badge/matplotlib-3.7+-11557c?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Portfolio_Project-blue?style=flat-square)

A Python strategy planning tool for endurance sportscar racing — built for portfolio use when targeting race engineering and strategy roles in championships such as **Lamera Cup**, **Fun Cup**, **ELMS**, and **WEC**.

The planner computes fuel-limited stint lengths, driver rotations with regulatory min/max drive times, pit window targets, and Safety Car re-plans — outputting strategist-ready tables and timeline charts.

---

## Why This Project?

Endurance race strategy lives or dies on **fuel windows**, **driver quotas**, and **pit timing**. This tool automates the pre-race plan a strategist would sketch on the pit wall — then lets you re-plan instantly when a Safety Car drops.

Built to demonstrate:
- Applied Python for real motorsport operations
- Understanding of FIA driver categories (Pro / Silver / Bronze)
- Fuel-limited stint geometry and pit window framing
- Dynamic re-planning under Safety Car conditions

---

## Screenshots

### Fun Cup — 4h Portimão (Pro + Bronze)

```bash
python endurance_stint_planner.py --preset fun-cup --output docs/fun_cup_timeline.png
```

![Fun Cup stint timeline](docs/fun_cup_timeline.png)

### ELMS — 6h Spa LMGT3 (Pro + Silver + Bronze)

```bash
python endurance_stint_planner.py --preset elms --output docs/elms_timeline.png
```

![ELMS stint timeline](docs/elms_timeline.png)

---

## Author

**Sreenath R.** — ESSEC MIM 2026

Motorsport strategy enthusiast with a focus on endurance race operations, fuel-window optimisation, and driver-management compliance. This project demonstrates applied Python for real pit-wall decision support.

**GitHub:** [@Dabi-init](https://github.com/Dabi-init)

---

## Features

| Module | Description |
|--------|-------------|
| **Fuel Calculator** | Derives laps and minutes per stint from tank capacity, consumption, and safety margin |
| **Driver Rotation** | Rotates Pro / Silver / Bronze drivers with per-stint and total-drive regulatory limits |
| **Pit Window Planner** | Computes earliest and latest pit entry for each stop |
| **Safety Car Re-plan** | Rebuilds remaining stints after SC deployment with extended stint and reduced pit loss |
| **Table Output** | Clean pandas DataFrame printed to terminal or exported to CSV |
| **Timeline Chart** | Matplotlib Gantt-style stint visualisation with pit window markers |

---

## Installation

### Prerequisites

- Python 3.10 or later
- pip

### Setup

```bash
git clone https://github.com/Dabi-init/endurance-stint-planner.git
cd endurance-stint-planner
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Quick Start

Run a built-in championship preset:

```bash
python endurance_stint_planner.py --preset fun-cup
```

Generate a stint timeline and save it:

```bash
python endurance_stint_planner.py --preset elms --plot --output outputs/elms_spa.png
```

Simulate a Safety Car re-plan:

```bash
python endurance_stint_planner.py --preset wec --safety-car 185 --extend-stint 8
```

Export the stint table to CSV:

```bash
python endurance_stint_planner.py --preset fun-cup --export-csv outputs/fun_cup_stints.csv
```

---

## Example Usage — Fun Cup 4h Portimão

This example mirrors a realistic **Fun Cup / Lamera Cup** 4-hour GT4 race with a **Pro + Bronze** driver lineup.

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Race duration | 4 hours (240 min) | Standard Fun Cup race length |
| Lap time | 2:08 (128 s) | Portimão GT4 race pace |
| Fuel tank | 80 L | GT4 tank size |
| Consumption | 2.6 L/lap | Measured long-run average |
| Safety margin | 1 lap | Protects against consumption drift |
| Pit loss | 50 s | In-lap + stop + out-lap delta |
| Bronze min total drive | 96 min (~40%) | Typical Bronze drive-time requirement |

### Command

```bash
python endurance_stint_planner.py --preset fun-cup
```

### Expected Output (abridged)

```
Fuel geometry: 29 laps/stint (1:01:52)
Lap time: 128.000s  |  Consumption: 2.60 L/lap  |  Tank: 80 L

====================================================================================================
  STINT PLAN — Fun Cup — 4h Portimão
====================================================================================================
 Stint       Driver Category   Start     End Duration  Laps  Fuel (L)  ...
     1   Martin Pro      Pro    5:00 1:06:52  1:01:52    29      75.4  ...
     2 Lucas Bronze   Bronze 1:07:42 2:09:34  1:01:52    29      75.4  ...
     3   Martin Pro      Pro 2:10:24 3:12:16  1:01:52    29      75.4  ...
     4 Lucas Bronze   Bronze 3:13:06 3:57:54    44:48    21      54.6  ...
====================================================================================================

Total stints: 4  |  Pit stops: 3

Driver totals:
  Martin Pro            2:03:44  (51.6% of race)
  Lucas Bronze          1:46:40  (44.4% of race)
```

### Safety Car Scenario

SC deploys at **2:05:00** while the Pro is on stint 3. Strategy extends the stint by 8 minutes to bunch the field, then pits under SC:

```bash
python endurance_stint_planner.py --preset fun-cup --safety-car 125 --extend-stint 8 --sc-pit-loss 25
```

The re-planner:
1. Extends the active stint under SC
2. Applies reduced pit loss (25 s vs 50 s green-flag)
3. Recalculates remaining stints with adjusted fuel margin
4. Re-validates Bronze minimum total drive time

---

## Custom Race Configuration

```bash
python endurance_stint_planner.py \
  --race-hours 6 \
  --race-name "ELMS Test Day" \
  --lap-time 2:22 \
  --tank 110 \
  --fuel-per-lap 3.1 \
  --pit-loss 48 \
  --drivers "Antoine:Pro::120:0,Sophie:Bronze:45:65:144,James:Silver::90:0"
```

Driver spec format: `Name:Category:min_stint:max_stint:min_total_drive` (minutes). Empty fields use defaults.

---

## Strategy Logic

### 1. Fuel-Limited Stint Length

```
usable_fuel = tank_capacity − (safety_laps × consumption_per_lap)
laps_per_stint = floor(usable_fuel / consumption_per_lap)
stint_duration = laps_per_stint × lap_time
```

The safety margin prevents running dry due to traffic, tyre degradation (higher fuel use), or Safety Car periods at higher consumption.

### 2. Driver Rotation

Each stint is assigned to the current driver in the rotation. The effective stint cap is:

```
min(fuel_limited_stint, driver_max_stint, remaining_race_time)
```

Non-final stints are floored to the driver's **minimum stint** where possible. Bronze drivers are capped at **65 minutes** per stint (WEC/ELMS regulation).

After each stop, the next driver in the lineup takes over. Total drive time per driver is tracked and validated against minimum requirements.

### 3. Pit Windows

For each non-final stint:

- **Window open** = stint start + driver minimum stint
- **Window close** = stint end (fuel limit)

These brackets define when the strategist can call the car without breaking regulations or risking fuel starvation.

### 4. Safety Car Re-plan

When `--safety-car` is triggered:

1. Completed stints before SC deployment are preserved
2. The active stint can be extended (`--extend-stint`) to gain track position
3. Pit loss is reduced (`--sc-pit-loss`, default 25 s)
4. Remaining race time is recalculated and a new stint sequence is generated
5. Fuel safety margin may be relaxed by 1 lap (fuel saved under SC pace)

---

## Built-in Presets

| Preset | Championship | Duration | Lineup |
|--------|-------------|----------|--------|
| `fun-cup` | Fun Cup / Lamera Cup GT4 | 4 h | Pro + Bronze |
| `elms` | ELMS LMGT3 | 6 h | Pro + Silver + Bronze |
| `wec` | WEC Hypercar | 6 h | Pro + Pro + Bronze |

---

## CLI Reference

```
usage: endurance_stint_planner.py [-h] [--preset {fun-cup,elms,wec}]
                                  [--race-hours RACE_HOURS] [--race-name RACE_NAME]
                                  [--lap-time LAP_TIME] [--tank TANK]
                                  [--fuel-per-lap FUEL_PER_LAP] [--safety-laps SAFETY_LAPS]
                                  [--pit-loss PIT_LOSS] [--drivers DRIVERS] [--plot]
                                  [--output OUTPUT] [--export-csv EXPORT_CSV]
                                  [--safety-car MINUTE] [--extend-stint EXTEND_STINT]
                                  [--sc-pit-loss SC_PIT_LOSS]
```

---

## Project Structure

```
endurance-stint-planner/
├── endurance_stint_planner.py   # Main application (CLI + all logic)
├── requirements.txt             # Python dependencies
├── LICENSE                      # MIT licence
├── README.md                    # This file
├── docs/                        # Timeline screenshots for README
├── .gitignore
└── outputs/                     # Generated charts and CSV (git-ignored)
```

---

## Future Improvements

- [ ] **Live timing integration** — ingest sector times and consumption from ECU telemetry or CSV logs
- [ ] **Tyre stint modelling** — compound degradation curves and mandatory change windows
- [ ] **Traffic-aware fuel correction** — adjust consumption for class traffic density
- [ ] **Multi-car offset planner** — undercut/overcut windows relative to rivals
- [ ] **Balance of Performance** — tank capacity adjustments per BOP revision
- [ ] **Web dashboard** — Streamlit or Flask UI for real-time strategist use
- [ ] **Unit tests** — pytest coverage for regulatory edge cases (Bronze 65 min cap, final stint partial fuel)
- [ ] **PDF race plan export** — formatted document for driver briefing packs

---

## Licence

MIT — see [LICENSE](LICENSE) for details.

---

## Contact

**Sreenath R.** — ESSEC MIM 2026

For strategy, data, or engineering opportunities in endurance sportscar racing, connect via [GitHub](https://github.com/Dabi-init).