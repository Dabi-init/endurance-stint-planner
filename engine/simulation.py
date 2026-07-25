"""Seeded uncertainty simulation around the transparent deterministic planner."""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass

from engine.models import RaceConfig
from engine.planner import PlanOptions, compute_plan


@dataclass(frozen=True)
class UncertaintyModel:
    pace_p10_sec: float
    pace_p90_sec: float
    fuel_p10_l_per_lap: float
    fuel_p90_l_per_lap: float
    source: str
    confidence: str


@dataclass(frozen=True)
class SimulationSummary:
    iterations: int
    feasible_rate: float
    laps_p10: float
    laps_median: float
    laps_p90: float
    pit_stops_median: float
    extra_stop_probability: float
    source: str
    confidence: str
    seed: int

    @property
    def lap_spread(self) -> float:
        return self.laps_p90 - self.laps_p10


def default_uncertainty(config: RaceConfig) -> UncertaintyModel:
    """Conservative manual ranges when no measured distribution is available."""
    return UncertaintyModel(
        pace_p10_sec=config.base_lap_time_sec * 0.992,
        pace_p90_sec=config.base_lap_time_sec * 1.008,
        fuel_p10_l_per_lap=config.fuel_consumption_per_lap * 0.97,
        fuel_p90_l_per_lap=config.fuel_consumption_per_lap * 1.03,
        source="Generic ±0.8% pace / ±3% fuel assumption",
        confidence="Low",
    )


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _ordered_bounds(low: float, mode: float, high: float) -> tuple[float, float, float]:
    values = sorted((max(low, 1e-6), max(mode, 1e-6), max(high, 1e-6)))
    return values[0], values[1], values[2]


def simulate_plan(
    config: RaceConfig,
    options: PlanOptions,
    uncertainty: UncertaintyModel | None = None,
    *,
    iterations: int = 200,
    seed: int = 20260725,
) -> SimulationSummary:
    """Run bounded pace/fuel scenarios with a fixed seed for reproducibility."""
    model = uncertainty or default_uncertainty(config)
    count = min(max(int(iterations), 20), 1000)
    rng = random.Random(seed)
    pace_low, pace_mode, pace_high = _ordered_bounds(
        model.pace_p10_sec,
        config.base_lap_time_sec,
        model.pace_p90_sec,
    )
    fuel_low, fuel_mode, fuel_high = _ordered_bounds(
        model.fuel_p10_l_per_lap,
        config.fuel_consumption_per_lap,
        model.fuel_p90_l_per_lap,
    )

    baseline = compute_plan(config, options)
    baseline_stops = baseline.total_pit_stops
    laps: list[float] = []
    stops: list[float] = []
    feasible_count = 0
    extra_stop_count = 0
    for _ in range(count):
        sampled = RaceConfig.from_dict(config.to_dict())
        sampled.base_lap_time_sec = rng.triangular(pace_low, pace_high, pace_mode)
        sampled.fuel_consumption_per_lap = rng.triangular(
            fuel_low, fuel_high, fuel_mode
        )
        plan = compute_plan(sampled, options)
        laps.append(float(plan.predicted_laps))
        stops.append(float(plan.total_pit_stops))
        if plan.is_feasible:
            feasible_count += 1
        if plan.total_pit_stops > baseline_stops:
            extra_stop_count += 1

    return SimulationSummary(
        iterations=count,
        feasible_rate=feasible_count / count,
        laps_p10=_quantile(laps, 0.10),
        laps_median=statistics.median(laps),
        laps_p90=_quantile(laps, 0.90),
        pit_stops_median=statistics.median(stops),
        extra_stop_probability=extra_stop_count / count,
        source=model.source,
        confidence=model.confidence,
        seed=seed,
    )
