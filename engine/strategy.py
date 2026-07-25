"""Generate, simulate, and rank explainable race-strategy alternatives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.models import PlanResult, RaceConfig
from engine.planner import PlanOptions, compute_plan
from engine.simulation import (
    SimulationSummary,
    UncertaintyModel,
    default_uncertainty,
    simulate_plan,
)

if TYPE_CHECKING:
    from engine.telemetry import TelemetryCalibration


@dataclass
class StrategyOutcome:
    name: str
    intent: str
    options: PlanOptions
    plan: PlanResult
    simulation: SimulationSummary
    rank: int = 0
    preferred: bool = False
    risk: str = "Unknown"
    ranking_reason: str = ""

    def to_row(self) -> dict[str, object]:
        return {
            "Rank": self.rank,
            "Strategy": self.name,
            "Recommended": self.preferred,
            "Feasible": self.plan.is_feasible,
            "Projected laps": self.plan.predicted_laps,
            "P10 laps": round(self.simulation.laps_p10, 1),
            "Median laps": round(self.simulation.laps_median, 1),
            "P90 laps": round(self.simulation.laps_p90, 1),
            "Pit stops": self.plan.total_pit_stops,
            "Pit time (s)": round(self.plan.total_pit_time_sec, 1),
            "Fuel used (L)": round(self.plan.total_fuel_used_liters, 1),
            "Reserve laps": self.options.resolved_reserve_laps(self.plan.config),
            "Extra-stop risk": f"{self.simulation.extra_stop_probability:.0%}",
            "Risk": self.risk,
        }


@dataclass
class StrategyComparison:
    outcomes: list[StrategyOutcome]
    uncertainty: UncertaintyModel

    @property
    def preferred(self) -> StrategyOutcome:
        return next(outcome for outcome in self.outcomes if outcome.preferred)

    def rows(self) -> list[dict[str, object]]:
        return [outcome.to_row() for outcome in self.outcomes]


def _uncertainty_from_calibration(
    config: RaceConfig,
    calibration: TelemetryCalibration | None,
) -> UncertaintyModel:
    if (
        calibration is None
        or calibration.lap_time_p10_sec is None
        or calibration.lap_time_p90_sec is None
        or calibration.fuel_burn_p10_l_per_lap is None
        or calibration.fuel_burn_p90_l_per_lap is None
    ):
        return default_uncertainty(config)
    return UncertaintyModel(
        pace_p10_sec=calibration.lap_time_p10_sec,
        pace_p90_sec=calibration.lap_time_p90_sec,
        fuel_p10_l_per_lap=calibration.fuel_burn_p10_l_per_lap,
        fuel_p90_l_per_lap=calibration.fuel_burn_p90_l_per_lap,
        source=calibration.source_label,
        confidence=calibration.confidence,
    )


def _candidate_options(config: RaceConfig) -> list[tuple[str, str, PlanOptions]]:
    base_reserve = max(config.regulations.fuel_safety_laps, 0)
    return [
        (
            "Conservative",
            "Adds one reserve lap to protect against burn-model error.",
            PlanOptions(
                name="Conservative",
                reserve_laps=base_reserve + 1,
                fuel_save_pct=0.0,
            ),
        ),
        (
            "Balanced",
            "Uses the configured reserve and central pace/fuel estimates.",
            PlanOptions(
                name="Balanced",
                reserve_laps=base_reserve,
                fuel_save_pct=0.0,
            ),
        ),
        (
            "Fuel Save",
            ("Targets 5% lower fuel burn with the configured, explicit pace penalty."),
            PlanOptions(
                name="Fuel Save",
                reserve_laps=base_reserve,
                fuel_save_pct=5.0,
            ),
        ),
    ]


def _risk_label(outcome: StrategyOutcome) -> str:
    if not outcome.plan.is_feasible:
        return "Critical"
    if outcome.simulation.feasible_rate < 0.80:
        return "High"
    if (
        outcome.simulation.extra_stop_probability >= 0.20
        or outcome.simulation.lap_spread >= 2.0
    ):
        return "Medium"
    return "Low"


def _rank_key(outcome: StrategyOutcome) -> tuple[float, ...]:
    """Visible lexicographic ranking, intentionally not a hidden weighted score."""
    return (
        1.0 if outcome.plan.is_feasible else 0.0,
        outcome.simulation.laps_median,
        outcome.simulation.laps_p10,
        float(outcome.plan.predicted_laps),
        -outcome.plan.total_pit_time_sec,
        -outcome.simulation.extra_stop_probability,
        float(outcome.options.resolved_reserve_laps(outcome.plan.config)),
    )


def compare_strategies(
    config: RaceConfig,
    calibration: TelemetryCalibration | None = None,
    *,
    iterations: int = 160,
    seed: int = 20260725,
) -> StrategyComparison:
    """Compare three intentional candidates under the same uncertainty model."""
    uncertainty = _uncertainty_from_calibration(config, calibration)
    outcomes: list[StrategyOutcome] = []
    for name, intent, options in _candidate_options(config):
        plan = compute_plan(config, options)
        simulation = simulate_plan(
            config,
            options,
            uncertainty,
            iterations=iterations,
            seed=seed,
        )
        outcome = StrategyOutcome(name, intent, options, plan, simulation)
        outcome.risk = _risk_label(outcome)
        outcomes.append(outcome)

    ranked = sorted(outcomes, key=_rank_key, reverse=True)
    for rank, outcome in enumerate(ranked, start=1):
        outcome.rank = rank
        outcome.preferred = rank == 1
        outcome.ranking_reason = (
            "Ranked by feasibility → median laps → P10 laps → central laps → "
            "pit time → extra-stop probability → reserve laps."
        )
    return StrategyComparison(ranked, uncertainty)
