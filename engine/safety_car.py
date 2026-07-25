"""Transparent Safety Car scenario modelling for pre-race what-if analysis."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from engine.models import Infeasibility, PlanResult, RaceConfig, format_duration
from engine.planner import PlanOptions, compute_plan
from engine.regulations import check_compliance


@dataclass(frozen=True)
class SafetyCarConfig:
    deploy_min: float
    duration_min: float
    lap_time_multiplier: float = 1.4
    sc_pit_loss_sec: float = 25.0
    pull_pit_into_sc: bool = True
    fuel_burn_multiplier: float = 0.55


@dataclass
class SafetyCarComparison:
    original: PlanResult
    replanned: PlanResult
    time_delta_min: float = 0.0
    pit_stops_moved: list[str] = field(default_factory=list)
    fuel_saved_liters: float = 0.0
    notes: list[str] = field(default_factory=list)
    confidence: str = "Scenario estimate"

    @property
    def time_gained(self) -> bool:
        return self.time_delta_min > 0.01


def _map_equivalent_time(
    time_min: float,
    deploy_min: float,
    sc_duration_min: float,
    pace_multiplier: float,
) -> float:
    """Map a green-equivalent race clock back to scheduled wall-clock time."""
    compressed_sc_end = deploy_min + sc_duration_min / pace_multiplier
    lost_min = sc_duration_min - sc_duration_min / pace_multiplier
    if time_min <= deploy_min:
        return time_min
    if time_min <= compressed_sc_end:
        return deploy_min + (time_min - deploy_min) * pace_multiplier
    return time_min + lost_min


def _weighted_burn(
    config: RaceConfig,
    deploy_min: float,
    duration_min: float,
    pace_multiplier: float,
    sc_burn_multiplier: float,
) -> float:
    """Estimate average per-lap burn from expected green and SC laps."""
    race_min = config.race_duration_min
    green_min = max(race_min - duration_min, 0.0)
    green_laps = green_min * 60.0 / max(config.base_lap_time_sec, 1.0)
    sc_laps = duration_min * 60.0 / max(config.base_lap_time_sec * pace_multiplier, 1.0)
    total_laps = green_laps + sc_laps
    if total_laps <= 0:
        return config.fuel_consumption_per_lap
    weighted_multiplier = (green_laps + sc_laps * sc_burn_multiplier) / total_laps
    return config.fuel_consumption_per_lap * weighted_multiplier


def _apply_single_sc_pit_opportunity(
    plan: PlanResult,
    sc: SafetyCarConfig,
    deploy: float,
    sc_end: float,
) -> list[str]:
    """Apply reduced transit loss to one stop already inside the SC window."""
    if not sc.pull_pit_into_sc:
        return []
    candidates = [
        stint
        for stint in plan.stints[:-1]
        if deploy <= stint.end_min <= sc_end and stint.pit_time_after_sec > 0
    ]
    if not candidates:
        return []

    selected = min(
        candidates,
        key=lambda stint: abs(stint.end_min - (deploy + sc_end) / 2.0),
    )
    normal_transit = max(plan.config.pit_stop_time_loss_sec, 0.0)
    saving = max(normal_transit - max(sc.sc_pit_loss_sec, 0.0), 0.0)
    if saving <= 0:
        return []

    selected.pit_time_after_sec = max(selected.pit_time_after_sec - saving, 0.0)
    selected.notes = (selected.notes + " | SC pit-lane transit").strip(" |")
    selected_index = plan.stints.index(selected)
    for later in plan.stints[selected_index + 1 :]:
        later.start_min -= saving / 60.0
    plan.total_pit_time_sec = max(plan.total_pit_time_sec - saving, 0.0)
    plan.time_margin_at_flag_min += saving / 60.0
    return [
        (
            f"Stop after stint {selected.stint_number} occurs inside the SC "
            f"window at {format_duration(selected.end_min)}; only this stop "
            f"receives the {saving:.1f}s transit saving."
        )
    ]


def _unchanged_comparison(
    original: PlanResult,
    note: str,
) -> SafetyCarComparison:
    return SafetyCarComparison(
        original=original,
        replanned=deepcopy(original),
        notes=[note],
        confidence="Not evaluated",
    )


def replan_with_safety_car(
    original: PlanResult,
    sc: SafetyCarConfig,
) -> SafetyCarComparison:
    """Re-estimate a plan for one declared SC window without hiding assumptions."""
    try:
        if not original.is_feasible:
            return SafetyCarComparison(
                original,
                PlanResult(
                    config=original.config,
                    infeasibilities=deepcopy(original.infeasibilities),
                ),
                notes=["Original strategy is infeasible; SC scenario not evaluated."],
                confidence="Not evaluated",
            )

        config = original.config
        race_end = config.race_duration_min
        deploy = min(max(sc.deploy_min, 0.0), race_end)
        duration = min(max(sc.duration_min, 0.0), max(race_end - deploy, 0.0))
        multiplier = max(sc.lap_time_multiplier, 1.0)
        burn_multiplier = min(max(sc.fuel_burn_multiplier, 0.05), 1.0)
        sc_end = deploy + duration

        if duration <= 0:
            return _unchanged_comparison(
                original, "SC duration is zero; plan unchanged."
            )
        if deploy >= race_end - 0.01:
            return _unchanged_comparison(
                original, "SC starts at the chequered flag; plan unchanged."
            )

        green_equivalent_loss = duration * (1.0 - 1.0 / multiplier)
        adjusted = RaceConfig.from_dict(config.to_dict())
        adjusted.race_duration_hours = (race_end - green_equivalent_loss) / 60.0
        adjusted.fuel_consumption_per_lap = _weighted_burn(
            config,
            deploy,
            duration,
            multiplier,
            burn_multiplier,
        )
        adjusted.data_source = f"{config.data_source} + declared Safety Car scenario"

        strategy = PlanOptions(name=f"{original.strategy_name} + SC")
        replanned = compute_plan(adjusted, strategy)
        if not replanned.stints:
            return SafetyCarComparison(
                original,
                replanned,
                notes=["SC-adjusted planning produced no complete stint."],
                confidence="Low",
            )

        for stint in replanned.stints:
            old_end = stint.end_min
            mapped_start = _map_equivalent_time(
                stint.start_min, deploy, duration, multiplier
            )
            mapped_end = _map_equivalent_time(old_end, deploy, duration, multiplier)
            stint.start_min = mapped_start
            stint.duration_min = max(mapped_end - mapped_start, 0.0)

        # Restore the real race clock while retaining the scenario burn estimate.
        replanned.config.race_duration_hours = config.race_duration_hours
        replanned.time_margin_at_flag_min = max(
            race_end - replanned.stints[-1].end_min, 0.0
        )
        replanned.assumptions.extend(
            [
                (f"One SC from {format_duration(deploy)} to {format_duration(sc_end)}"),
                f"SC lap time ×{multiplier:.2f}",
                f"SC per-lap fuel burn ×{burn_multiplier:.2f}",
                "SC effect uses a green-equivalent pre-race approximation",
            ]
        )
        replanned.warnings.append(
            "Scenario only: no live race-control feed, traffic model, "
            "wave-by, class split, or pit-closure rule is included."
        )

        pit_notes = _apply_single_sc_pit_opportunity(replanned, sc, deploy, sc_end)
        if sc.pull_pit_into_sc and not pit_notes:
            pit_notes.append(
                "No planned stop falls inside the SC window; no pit saving applied."
            )

        compliance = check_compliance(replanned)
        if not compliance.all_passed:
            replanned.infeasibilities.append(
                Infeasibility(
                    "sc_driver_rule_risk",
                    (
                        "The slower SC clock creates a configured driver-rule "
                        "conflict in this scenario."
                    ),
                    "Move a driver change or check the event-specific SC rules.",
                )
            )

        replanned.total_fuel_used_liters = sum(
            stint.fuel_used_liters for stint in replanned.stints
        )
        fuel_saved = original.total_fuel_used_liters - replanned.total_fuel_used_liters
        time_delta = (
            replanned.time_margin_at_flag_min - original.time_margin_at_flag_min
        )
        notes = [
            (
                f"SC window {format_duration(deploy)}–"
                f"{format_duration(sc_end)} changes the green-equivalent race "
                f"clock by {green_equivalent_loss:.1f} min."
            ),
            (
                "The pace and fuel multipliers are explicit scenario inputs, "
                "not telemetry-derived facts."
            ),
            *pit_notes,
        ]
        return SafetyCarComparison(
            original=original,
            replanned=replanned,
            time_delta_min=time_delta,
            pit_stops_moved=pit_notes,
            fuel_saved_liters=fuel_saved,
            notes=notes,
            confidence="Medium-low: deterministic pre-race scenario",
        )
    except Exception as exc:
        fallback = deepcopy(original)
        fallback.infeasibilities.append(
            Infeasibility(
                "sc_scenario_error",
                f"Safety Car scenario failed safely: {exc}",
                "Reset the SC inputs and retry.",
            )
        )
        return SafetyCarComparison(
            original,
            fallback,
            notes=[f"SC scenario failed safely: {exc}"],
            confidence="Not evaluated",
        )
