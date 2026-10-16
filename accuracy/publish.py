"""Read and write the derived season log, and the static GitHub Pages file."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

from accuracy.score import (
    ASSUMPTION,
    HONESTY,
    NOTICE,
    recommend,
    score_race,
    season_rates,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
PAGES_PATH = Path(__file__).resolve().parent.parent / "docs" / "accuracy" / "index.html"


def log_path(season: int, root: Path | None = None) -> Path:
    return (root or DATA_DIR) / f"{season}.json"


def read_log(season: int, root: Path | None = None) -> dict[str, object] | None:
    path = log_path(season, root)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"The accuracy log for {season} is not an object.")
    return payload


def write_log(payload: dict[str, object], root: Path | None = None) -> Path:
    path = log_path(int(payload["season"]), root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def build_log(
    races: list[dict[str, object]],
    *,
    season: int,
    as_of: str,
    previous: dict[str, object] | None = None,
    refresh: bool = False,
) -> dict[str, object]:
    """Score new races and keep derived rows already stored for this season."""
    kept: list[dict[str, object]] = []
    if previous and not refresh:
        for race in previous.get("races") or []:
            if isinstance(race, dict):
                kept.append(race)
    seen = {(str(race["race_date"]), str(race["event_name"])) for race in kept}
    for actual in races:
        key = (str(actual["race_date"]), str(actual["event_name"]))
        if key in seen:
            continue
        laps = int(actual["race_laps"])
        if laps < 1:
            continue
        plan = recommend(season, int(actual["round"]), laps)
        kept.append(score_race(actual, plan))
        seen.add(key)
    kept.sort(key=lambda race: (str(race["race_date"]), str(race["event_name"])))
    for index, race in enumerate(kept, start=1):
        race["round"] = index
    rates = season_rates(kept)
    return {
        "season": season,
        "as_of": as_of,
        "notice": NOTICE,
        "honesty": HONESTY,
        "assumption": ASSUMPTION,
        "rates": rates,
        "races": kept,
    }


def render_page(payload: dict[str, object]) -> str:
    """Static page. No script, no remote asset, no tracker."""
    rates = payload["rates"]
    races = payload["races"]
    assert isinstance(rates, dict)
    assert isinstance(races, list)
    rows = "\n".join(_race_row(race, index == 0) for index, race in enumerate(races))
    if not rows:
        rows = "<p>No completed race is in this log yet.</p>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pitwall accuracy log {escape(str(payload["season"]))}</title>
<meta name="robots" content="index, follow">
<meta name="description" content="Post-session accuracy log for the Pitwall planner. Unofficial, not affiliated with Formula 1.">
<style>
:root {{ color-scheme: dark; --bg:#07090e; --panel:#101720; --line:rgba(232,240,250,.12); --text:#f4f7fb; --muted:#9aafc4; --cyan:#3ee0c5; --amber:#ffb020; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 "Segoe UI", Helvetica, Arial, sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:28px 18px 64px; }}
h1 {{ font-size:1.8rem; margin:0 0 8px; }}
h2 {{ font-size:1.15rem; margin:28px 0 8px; }}
p {{ margin:0 0 12px; }}
.notice {{ border-left:3px solid var(--amber); background:rgba(255,176,32,.08); padding:12px 14px; }}
.muted {{ color:var(--muted); }}
.rates {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; margin:16px 0 8px; }}
.rate {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:12px; }}
.rate span {{ display:block; color:var(--muted); font-size:.78rem; letter-spacing:.04em; text-transform:uppercase; }}
.rate strong {{ font-size:1.35rem; }}
details {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px 12px; margin:8px 0; }}
summary {{ cursor:pointer; }}
table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--muted); font-weight:600; }}
a {{ color:var(--cyan); }}
</style>
</head>
<body>
<main>
<p class="notice"><strong>{escape(str(payload["notice"]))}</strong></p>
<h1>{escape(str(payload["season"]))} accuracy log</h1>
<p class="muted">Through {escape(str(payload["as_of"]))}. {escape(str(payload["honesty"]))}</p>
<p class="muted">{escape(str(payload["assumption"]))}</p>
<section class="rates" aria-label="Season error rates">
{_rate("Pit-lap error", _laps(rates.get("pit_lap_mae")))}
{_rate("Stint-length error", _laps(rates.get("stint_length_mae")))}
{_rate("Stop-count error", _laps(rates.get("stop_count_mae")))}
{_rate("Undercut error", _percent(rates.get("undercut_error_rate")))}
{_rate("Finish-order error", _laps(rates.get("finish_order_mae")))}
</section>
<p class="muted">{int(rates.get("races") or 0)} races in the log. {int(rates.get("strategy_races") or 0)} use the dry assumption pack. {int(rates.get("undercut_pairs") or 0)} grid-adjacent pairs, {int(rates.get("undercut_hits") or 0)} undercut calls matched.</p>
<h2>Season log</h2>
{rows}
<p class="muted"><a href="../index.html">Pitwall Agent</a></p>
</main>
</body>
</html>
"""


def write_page(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or PAGES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_page(payload), encoding="utf-8")
    return target


def _rate(label: str, value: str) -> str:
    return f'<p class="rate"><span>{escape(label)}</span><strong>{escape(value)}</strong></p>'


def _laps(value: object) -> str:
    if value is None:
        return "—"
    return f"{float(value):.3f}"


def _percent(value: object) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _race_row(race: object, open_details: bool) -> str:
    assert isinstance(race, dict)
    rates = race["rates"]
    assert isinstance(rates, dict)
    note = ""
    if race.get("wet_tyres_seen"):
        note = " Wet tyres were in the stints, so this race stays out of the strategy rates."
    if not race.get("plan_feasible"):
        note += " The planner had no legal plan."
    open_attr = " open" if open_details else ""
    return f"""<details{open_attr}>
<summary>Round {int(race["round"])} · {escape(str(race["event_name"]))} · {escape(str(race["race_date"]))} · pit {_laps(rates.get("pit_lap_mae"))} · stints {_laps(rates.get("stint_length_mae"))} · undercut {_percent(rates.get("undercut_error_rate"))} · finish {_laps(rates.get("finish_order_mae"))}</summary>
<p class="muted">Predicted stops {escape(_join(race.get("predicted_stop_laps")))} · predicted stints {escape(_join(race.get("predicted_stint_laps")))}.{escape(note)} {escape(str(race.get("plan_message") or ""))}</p>
<table>
<thead><tr><th>Driver</th><th>Qualifying</th><th>Finish</th><th>Actual stops</th><th>Actual stints</th><th>Pit error</th><th>Stint error</th></tr></thead>
<tbody>
{"".join(_driver_row(driver) for driver in race["drivers"])}
</tbody>
</table>
</details>"""


def _driver_row(driver: object) -> str:
    assert isinstance(driver, dict)
    finish = driver.get("actual_finish_rank")
    finish_text = "—" if finish is None else str(finish)
    if driver.get("status") not in {None, "", "classified"}:
        finish_text = str(driver["status"])
    return (
        "<tr>"
        f"<td>{escape(str(driver['code']))}</td>"
        f"<td>{escape(_pos(driver.get('qualifying_position')))}</td>"
        f"<td>{escape(finish_text)}</td>"
        f"<td>{escape(_join(driver.get('actual_stop_laps')))}</td>"
        f"<td>{escape(_join(driver.get('actual_stint_laps')))}</td>"
        f"<td>{escape(_laps(driver.get('pit_lap_mae')))}</td>"
        f"<td>{escape(_laps(driver.get('stint_length_mae')))}</td>"
        "</tr>"
    )


def _join(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "—"
    return ", ".join(str(value) for value in values)


def _pos(value: object) -> str:
    if value is None:
        return "—"
    return str(value)
