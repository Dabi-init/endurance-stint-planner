"""Seeded sensitivity for one F1 plan, and a small undercut sum.

The percentiles are a sample of the file's own degradation and pit-lane loss.
They are not a forecast and they are not a claim that the model is accurate.
"""

from __future__ import annotations

import random
from dataclasses import replace

from engine.f1 import F1Setup, StintRequest, score_stints

ODDS_HONESTY = (
    "These percentiles are a seeded sample of the file's degradation and pit-lane loss. "
    "They are not a P10–P90 forecast from race history, and they are not a validated prediction."
)


def undercut(
    *,
    gap_behind_sec: float,
    laps_ahead: int,
    tyre_gain_sec_per_lap: float,
    our_pit_loss_sec: float,
    their_pit_loss_sec: float,
) -> dict[str, object]:
    """Net gap after we stop `laps_ahead` laps before the rival and both have pitted.

    Positive net means we are ahead of that rival at the moment they stop.
    Tyre gain is an assumption you type in. It is not measured from a rival model.
    """
    if laps_ahead < 1:
        raise ValueError("laps_ahead must be at least 1")
    gained = tyre_gain_sec_per_lap * laps_ahead
    net = round(gained - our_pit_loss_sec + their_pit_loss_sec - gap_behind_sec, 3)
    span = "1 lap" if laps_ahead == 1 else f"{laps_ahead} laps"
    if net > 0:
        text = (
            f"Pit {span} earlier and this rival is {net:.3f} s behind when they stop."
        )
    elif net < 0:
        text = f"Pit {span} earlier and this rival is still {abs(net):.3f} s ahead when they stop."
    else:
        text = f"Pit {span} earlier and this rival is alongside when they stop."
    return {
        "net_sec": net,
        "ahead": net > 0,
        "tyre_gain_sec": round(gained, 3),
        "explanation": text,
        "assumption": "Tyre gain per lap is your input, not a measured rival.",
    }


def race_time_odds(
    setup: F1Setup,
    stints: list[tuple[str, int]],
    *,
    iterations: int = 64,
    seed: int = 20241015,
    pit_spread_sec: float = 1.0,
    deg_scale: float = 0.1,
) -> dict[str, object]:
    """Sample race time by nudging pit loss and degradation with a fixed seed."""
    if iterations < 1 or iterations > 400:
        raise ValueError("iterations must be from 1 to 400")
    if setup.pit_lane_loss_sec is None:
        raise ValueError("Add the pit-lane time loss in seconds.")
    rng = random.Random(seed)
    requests = [StintRequest(compound, laps) for compound, laps in stints]
    times: list[float] = []
    for _ in range(iterations):
        factor = 1 + rng.uniform(-deg_scale, deg_scale)
        pit = max(
            0.0, setup.pit_lane_loss_sec + rng.uniform(-pit_spread_sec, pit_spread_sec)
        )
        trial = _perturbed(setup, factor, pit)
        plan = score_stints(trial, requests, name="Sample")
        if plan.feasible and plan.race_time_sec is not None:
            times.append(plan.race_time_sec)
    times.sort()
    return {
        "iterations": iterations,
        "seed": seed,
        "feasible_runs": len(times),
        "p10_sec": _percentile(times, 0.10),
        "p50_sec": _percentile(times, 0.50),
        "p90_sec": _percentile(times, 0.90),
        "honesty": ODDS_HONESTY,
    }


def _perturbed(setup: F1Setup, deg_factor: float, pit_loss: float) -> F1Setup:
    trial = replace(setup)
    trial.compounds = [
        replace(compound, deg_sec_per_lap=compound.deg_sec_per_lap * deg_factor)
        for compound in setup.compounds
    ]
    trial.cars = list(setup.cars)
    trial.drivers = list(setup.drivers)
    trial.teams = list(setup.teams)
    trial.provenance = dict(setup.provenance)
    trial.assumptions = list(setup.assumptions)
    trial.pit_lane_loss_sec = pit_loss
    return trial


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    index = round((len(values) - 1) * fraction)
    return values[index]
