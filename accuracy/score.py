"""Compare one planner recommendation with recorded pit laps, stints, and order.

The arithmetic is exact and local. It does not fetch timing and it does not
claim the model has been validated.
"""

from __future__ import annotations

import itertools

from engine.f1 import best_f1_plan
from engine.series_config import apply_overrides, load_setup

NOTICE = "Unofficial, not affiliated with Formula 1."
ASSUMPTION = (
    "Pit-lane loss is 22 seconds, the base lap is 95 seconds, and compound life "
    "matches the bundled Bahrain assumption pack. The tank is 110 kg and the car "
    "uses 1 kg of fuel per lap, so a long race is not rejected for fuel. The same "
    "pack is used for every round. These are not measured 2026 circuit facts."
)
HONESTY = (
    "Not validated yet. This is a post-session score of that assumption pack "
    "against free OpenF1 or FastF1 results, not a live forecast and not a rival "
    "model. Predicted finish order is qualifying order, because the pack gives "
    "every car the same strategy time. An undercut is predicted only when the "
    "pack stops the car behind on an earlier lap than the car ahead."
)

# The Bahrain event file's compound life. Copied here so the accuracy job does
# not pretend each 2026 circuit has its own measured tyre model.
_COMPOUNDS = {
    "SOFT": {"max_laps": 22, "pace_delta_sec": -0.4, "deg_sec_per_lap": 0.06},
    "MEDIUM": {"max_laps": 32, "pace_delta_sec": 0.0, "deg_sec_per_lap": 0.035},
    "HARD": {"max_laps": 42, "pace_delta_sec": 0.35, "deg_sec_per_lap": 0.02},
}
_PIT_LOSS_SEC = 22.0
_BASE_LAP_SEC = 95.0
_FUEL_CAPACITY_KG = 110.0
_FUEL_PER_LAP_KG = 1.0


def recommend(season: int, round_: int, race_laps: int) -> dict[str, object]:
    """Run the deterministic planner once for the whole field."""
    setup = load_setup(
        season,
        round_,
        overrides={
            "race_laps": race_laps,
            "pit_lane_loss_sec": _PIT_LOSS_SEC,
            "base_lap_time_sec": _BASE_LAP_SEC,
            "dry_race": True,
            "compounds": _COMPOUNDS,
        },
    )
    car_id = setup.cars[0].car_id if setup.cars else "default"
    setup = apply_overrides(
        setup,
        {
            "cars": [
                {
                    "car_id": car_id,
                    "fuel_capacity_kg": _FUEL_CAPACITY_KG,
                    "starting_fuel_kg": _FUEL_CAPACITY_KG,
                    "fuel_consumption_kg_per_lap": _FUEL_PER_LAP_KG,
                }
            ]
        },
    )
    plan = best_f1_plan(setup)
    if not plan.feasible:
        message = (
            plan.infeasibilities[0].message
            if plan.infeasibilities
            else "No legal plan."
        )
        return {
            "feasible": False,
            "stop_laps": [],
            "stint_laps": [],
            "compounds": [],
            "message": message,
        }
    return {
        "feasible": True,
        "stop_laps": list(plan.stop_laps),
        "stint_laps": list(plan.stint_laps),
        "compounds": list(plan.compounds_used),
        "message": plan.summary,
    }


def score_race(race: dict[str, object], plan: dict[str, object]) -> dict[str, object]:
    """Score one race. ``race`` is the small derived actual, not a raw feed."""
    feasible = bool(plan.get("feasible"))
    wet = bool(race.get("wet_tyres_seen"))
    strategy_scored = feasible and not wet
    predicted_stops = [int(lap) for lap in plan.get("stop_laps", [])]
    predicted_stints = [int(lap) for lap in plan.get("stint_laps", [])]
    drivers_in = list(race.get("drivers") or [])
    scored_drivers = [
        _score_driver(
            driver,
            predicted_stops,
            predicted_stints,
            strategy_scored=strategy_scored,
        )
        for driver in drivers_in
    ]
    _assign_finish_ranks(scored_drivers)
    pairs = _undercut_pairs(scored_drivers) if strategy_scored else []
    return {
        "round": int(race["round"]),
        "event_name": str(race["event_name"]),
        "race_date": str(race["race_date"]),
        "meeting_key": race.get("meeting_key"),
        "race_laps": int(race["race_laps"]),
        "source": str(race.get("source") or ""),
        "wet_tyres_seen": wet,
        "strategy_scored": strategy_scored,
        "plan_feasible": feasible,
        "predicted_stop_laps": predicted_stops,
        "predicted_stint_laps": predicted_stints,
        "predicted_compounds": list(plan.get("compounds") or []),
        "plan_message": str(plan.get("message") or ""),
        "drivers": scored_drivers,
        "undercut_pairs": pairs,
        "rates": _race_rates(scored_drivers, pairs, strategy_scored),
    }


def season_rates(races: list[dict[str, object]]) -> dict[str, object]:
    """Average the published per-driver figures. Each included driver counts once."""
    pit: list[float] = []
    stints: list[float] = []
    stops: list[float] = []
    finish: list[float] = []
    hits = 0
    pairs = 0
    for race in races:
        for driver in race["drivers"]:
            if driver["strategy_scored"]:
                if driver["pit_lap_mae"] is not None:
                    pit.append(float(driver["pit_lap_mae"]))
                if driver["stint_length_mae"] is not None:
                    stints.append(float(driver["stint_length_mae"]))
                stops.append(float(driver["stop_count_abs"]))
            if driver["finish_scored"]:
                finish.append(
                    abs(
                        int(driver["predicted_finish_rank"])
                        - int(driver["actual_finish_rank"])
                    )
                )
        if race["strategy_scored"]:
            for pair in race["undercut_pairs"]:
                pairs += 1
                hits += int(bool(pair["hit"]))
    error = None if pairs == 0 else 1 - (hits / pairs)
    return {
        "races": len(races),
        "strategy_races": sum(1 for race in races if race["strategy_scored"]),
        "undercut_pairs": pairs,
        "undercut_hits": hits,
        "pit_lap_mae": rounded(average(pit)),
        "stint_length_mae": rounded(average(stints)),
        "stop_count_mae": rounded(average(stops)),
        "undercut_error_rate": rounded(error),
        "finish_order_mae": rounded(average(finish)),
    }


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def _mae(predicted: list[int], actual: list[int]) -> float | None:
    if not predicted or not actual:
        return None
    gaps = [abs(left - right) for left, right in zip(predicted, actual, strict=False)]
    return sum(gaps) / len(gaps)


def _score_driver(
    driver: dict[str, object],
    predicted_stops: list[int],
    predicted_stints: list[int],
    *,
    strategy_scored: bool,
) -> dict[str, object]:
    actual_stops = [int(lap) for lap in driver.get("stop_laps") or []]
    actual_stints = [int(lap) for lap in driver.get("stint_laps") or []]
    classified = bool(driver.get("classified"))
    included = strategy_scored and classified
    quali = driver.get("qualifying_position")
    return {
        "code": str(driver.get("code") or ""),
        "driver_number": int(driver["driver_number"]),
        "qualifying_position": None if quali is None else int(quali),
        "finish_position": (
            None
            if driver.get("finish_position") is None
            else int(driver["finish_position"])
        ),
        "status": str(driver.get("status") or ""),
        "classified": classified,
        "strategy_scored": included,
        "finish_scored": False,
        "predicted_finish_rank": None,
        "actual_finish_rank": None,
        "predicted_stop_laps": list(predicted_stops),
        "actual_stop_laps": actual_stops,
        "predicted_stint_laps": list(predicted_stints),
        "actual_stint_laps": actual_stints,
        "pit_lap_mae": rounded(_mae(predicted_stops, actual_stops))
        if included
        else None,
        "stint_length_mae": (
            rounded(_mae(predicted_stints, actual_stints)) if included else None
        ),
        "stop_count_abs": (
            abs(len(predicted_stops) - len(actual_stops)) if included else None
        ),
    }


def _assign_finish_ranks(drivers: list[dict[str, object]]) -> None:
    """Predicted rank is qualifying order. Actual rank is the classified order."""
    field = [
        driver
        for driver in drivers
        if driver["classified"]
        and driver["qualifying_position"] is not None
        and driver["finish_position"] is not None
    ]
    by_quali = sorted(
        field,
        key=lambda driver: (
            int(driver["qualifying_position"]),
            int(driver["driver_number"]),
        ),
    )
    by_finish = sorted(
        field,
        key=lambda driver: (
            int(driver["finish_position"] or 10_000),
            int(driver["driver_number"]),
        ),
    )
    for rank, driver in enumerate(by_quali, start=1):
        driver["predicted_finish_rank"] = rank
        driver["finish_scored"] = True
    for rank, driver in enumerate(by_finish, start=1):
        driver["actual_finish_rank"] = rank


def _undercut_pairs(drivers: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered = sorted(
        (
            driver
            for driver in drivers
            if driver["strategy_scored"] and driver["qualifying_position"] is not None
        ),
        key=lambda driver: (
            int(driver["qualifying_position"]),
            int(driver["driver_number"]),
        ),
    )
    pairs: list[dict[str, object]] = []
    for ahead, behind in itertools.pairwise(ordered):
        predicted = _earlier(
            behind["predicted_stop_laps"], ahead["predicted_stop_laps"]
        )
        actual = _earlier(behind["actual_stop_laps"], ahead["actual_stop_laps"])
        pairs.append(
            {
                "ahead": ahead["code"],
                "behind": behind["code"],
                "predicted": predicted,
                "actual": actual,
                "hit": predicted == actual,
            }
        )
    return pairs


def _earlier(behind_stops: list[int], ahead_stops: list[int]) -> bool:
    if not behind_stops or not ahead_stops:
        return False
    return behind_stops[0] < ahead_stops[0]


def _race_rates(
    drivers: list[dict[str, object]],
    pairs: list[dict[str, object]],
    strategy_scored: bool,
) -> dict[str, object]:
    return season_rates(
        [
            {
                "strategy_scored": strategy_scored,
                "drivers": drivers,
                "undercut_pairs": pairs,
            }
        ]
    )
