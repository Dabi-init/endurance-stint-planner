"""Build a replay script from a bundled fixture and the deterministic planner.

The script steps through the recorded stints. At the start, and at each
recorded pit, it asks the planner for a legal plan of the laps that remain.
Pace stays on the event file unless the caller asks for the same-race
clean-lap median. That median is not a pre-race forecast.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backtest.harness import BUNDLED_FIXTURES, load_actuals
from engine.f1 import F1Plan, F1Setup, best_f1_plan, legal_one_stop_window
from engine.series_config import IMAGE_POLICY, apply_overrides, colour_css, load_setup
from historical.models import RaceActuals

ENTRY_FILES = {
    "2024-r01-bahrain-verstappen": (
        Path(__file__).resolve().parent.parent
        / "backtest"
        / "fixtures"
        / "2024_r01_bahrain_entry.json"
    ),
}


@dataclass(frozen=True)
class ReplayScript:
    fixture_id: str
    payload: dict[str, Any]


def build_replay(
    fixture_id: str = "2024-r01-bahrain-verstappen",
    *,
    overrides: dict[str, Any] | None = None,
    anchor_pace: bool = False,
) -> ReplayScript:
    if fixture_id not in BUNDLED_FIXTURES:
        known = ", ".join(sorted(BUNDLED_FIXTURES))
        raise ValueError(
            f"Unknown replay fixture {fixture_id}. Known fixtures: {known}."
        )
    actuals = load_actuals(BUNDLED_FIXTURES[fixture_id])
    setup = load_setup(actuals.season, actuals.round)
    if overrides:
        setup = apply_overrides(setup, overrides)
    anchor = _maybe_anchor(setup, actuals, anchor_pace)
    setup = anchor or setup
    plan = best_f1_plan(setup)
    events = [_event(setup, plan, actuals, lap=0, kind="pre-race")]
    done_compounds: list[str] = []
    cursor = 0
    for stint in actuals.stints[:-1]:
        cursor += stint.laps
        done_compounds.append(stint.compound)
        sliced = _remaining_setup(setup, cursor, done_compounds)
        events.append(
            _event(
                sliced,
                best_f1_plan(sliced),
                actuals,
                lap=cursor,
                kind="recorded-pit",
            )
        )
    return ReplayScript(
        fixture_id=fixture_id,
        payload={
            "fixture_id": fixture_id,
            "event_name": actuals.event_name,
            "season": actuals.season,
            "round": actuals.round,
            "race_laps": actuals.race_laps,
            "focus_driver": actuals.driver_code,
            "focus_number": actuals.driver_number,
            "anchor_pace": anchor_pace,
            "pace_anchor_sec": (
                None
                if not anchor_pace or not actuals.clean_lap_durations_sec
                else float(statistics.median(actuals.clean_lap_durations_sec))
            ),
            "image_policy": IMAGE_POLICY,
            "honesty": _honesty(anchor_pace),
            "tower": _tower(fixture_id, actuals),
            "laps": _laps(actuals, setup),
            "recorded_stints": [
                {
                    "compound": stint.compound,
                    "label": stint.compound.title(),
                    "laps": stint.laps,
                    "colour": _colour(setup, stint.compound),
                    "tyre_age_at_start": stint.tyre_age_at_start,
                }
                for stint in actuals.stints
            ],
            "events": events,
        },
    )


def _maybe_anchor(
    setup: F1Setup, actuals: RaceActuals, enabled: bool
) -> F1Setup | None:
    if not enabled or not actuals.clean_lap_durations_sec:
        return None
    anchor = float(statistics.median(actuals.clean_lap_durations_sec))
    updated = apply_overrides(setup, {"base_lap_time_sec": anchor})
    updated.provenance["base_lap_time_sec"] = "recorded-pace"
    updated.assumptions.append(
        "Pace anchor is the median clean lap from this recorded session "
        f"({anchor:.3f} s). In-laps, out-laps, and lap 1 were left out. "
        "This is not a blind pre-race forecast."
    )
    return updated


def _remaining_setup(
    setup: F1Setup, laps_done: int, compounds_used: list[str]
) -> F1Setup:
    remaining = int(setup.race_laps or 0) - laps_done
    overrides: dict[str, Any] = {"race_laps": remaining}
    car = setup.cars[0] if setup.cars else None
    if (
        car is not None
        and car.starting_fuel_kg is not None
        and car.fuel_consumption_kg_per_lap is not None
    ):
        used = car.fuel_consumption_kg_per_lap * laps_done
        overrides["cars"] = [
            {
                "car_id": car.car_id,
                "starting_fuel_kg": round(car.starting_fuel_kg - used, 3),
            }
        ]
    distinct = {compound.upper() for compound in compounds_used}
    if setup.dry_race and len(distinct) >= setup.dry_min_compounds:
        overrides["rules"] = {"dry_min_compounds": 1}
    updated = apply_overrides(setup, overrides)
    names = ", ".join(compound.title() for compound in compounds_used)
    updated.assumptions.append(
        f"Replay slice after lap {laps_done}. {remaining} laps remain. "
        f"Tyres already used: {names}. "
        "Fuel left is the file's start load minus the file's consumption so far. "
        "The two-compound rule already counts those used tyres when two dry compounds are on the car."
    )
    return updated


def _event(
    setup: F1Setup,
    plan: F1Plan,
    actuals: RaceActuals,
    *,
    lap: int,
    kind: str,
) -> dict[str, Any]:
    window = None
    if len(plan.compounds_used) == 2:
        window = legal_one_stop_window(
            setup, plan.compounds_used[0], plan.compounds_used[1]
        )
    recorded = _recorded_at(actuals, lap)
    if kind == "pre-race":
        lead = "Before the lights, the file's fastest legal plan is the one below."
    else:
        lead = (
            f"Recorded pit at the end of lap {lap}, from {recorded}."
            " The plan below is a fresh plan for the laps that remain, not a rewrite of history."
        )
    return {
        "lap": lap,
        "kind": kind,
        "summary": plan.summary,
        "why": plan.why,
        "explanation": f"{lead} {plan.summary} {plan.why}".strip(),
        "feasible": plan.feasible,
        "race_time_sec": plan.race_time_sec,
        "pit_stops": plan.pit_stops,
        "stop_laps": list(plan.stop_laps),
        "pit_window": None if window is None else [window[0], window[1]],
        "stints": [
            {
                "compound": stint.compound_id,
                "label": stint.label,
                "laps": stint.laps,
                "start_lap": stint.start_lap,
                "end_lap": stint.end_lap,
                "stop_lap": stint.stop_lap,
                "colour": _colour(setup, stint.compound_id),
            }
            for stint in plan.stints
        ],
        "fuel_used_kg": plan.fuel_used_kg,
        "evidence_level": plan.evidence_level,
        "uncertainty": plan.uncertainty,
    }


def _recorded_at(actuals: RaceActuals, lap: int) -> str:
    if lap <= 0:
        return "the start"
    seen: list[str] = []
    covered = 0
    for stint in actuals.stints:
        covered += stint.laps
        seen.append(f"{stint.compound.title()} {stint.laps}")
        if covered >= lap:
            break
    return ", ".join(seen)


def _laps(actuals: RaceActuals, setup: F1Setup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lap = 1
    for index, stint in enumerate(actuals.stints):
        colour = _colour(setup, stint.compound)
        for offset in range(stint.laps):
            rows.append(
                {
                    "lap": lap,
                    "compound": stint.compound,
                    "colour": colour,
                    "pit": offset == stint.laps - 1 and index < len(actuals.stints) - 1,
                }
            )
            lap += 1
    return rows


def _colour(setup: F1Setup, compound_id: str) -> str:
    compound = setup.compound(compound_id)
    return "" if compound is None else compound.colour


def _tower(fixture_id: str, actuals: RaceActuals) -> list[dict[str, Any]]:
    path = ENTRY_FILES.get(fixture_id)
    if path is None or not path.is_file():
        return [
            {
                "driver_number": actuals.driver_number,
                "code": actuals.driver_code,
                "full_name": actuals.full_name,
                "team_name": actuals.team_name,
                "team_colour": actuals.team_colour,
                "team_colour_css": colour_css(actuals.team_colour),
                "headshot_url": actuals.headshot_url,
                "grid": None,
                "finish_position": None,
                "focus": True,
            }
        ]
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in document.get("drivers", []):
        colour = row.get("team_colour")
        rows.append(
            {
                "driver_number": row.get("driver_number"),
                "code": row.get("code"),
                "full_name": row.get("full_name"),
                "team_name": row.get("team_name"),
                "team_colour": colour,
                "team_colour_css": colour_css(colour),
                "headshot_url": row.get("headshot_url"),
                "country_code": row.get("country_code"),
                "grid": row.get("grid"),
                "finish_position": row.get("finish_position"),
                "focus": row.get("code") == actuals.driver_code,
            }
        )
    rows.sort(key=lambda item: (item["grid"] is None, item["grid"] or 0))
    return rows


def _honesty(anchor_pace: bool) -> str:
    base = (
        "Replay uses the recorded stints for car 1 only. "
        "Other cars are the entry list (grid and finish), not a lap feed. "
        "Compound life, degradation, and pit-lane loss stay file assumptions."
    )
    if anchor_pace:
        return (
            base
            + " The pace anchor is this car's clean-lap median from the same race, "
            "so a small time gap is not a blind pre-race forecast."
        )
    return base + " Pace is the event-file base lap, not a measured forecast."
