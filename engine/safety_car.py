"""Safety Car / incident re-planning with before/after comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from engine.models import Infeasibility, PlanResult, RaceConfig, Stint, format_duration
from engine.planner import (
    _RotationState,
    _build_plan_internal,
    compute_plan,
    laps_for_minutes,
    minutes_for_laps,
    pit_stop_duration_sec,
)
from engine.regulations import preflight_infeasibility_checks


@dataclass
class SafetyCarConfig:
    deploy_min: float
    duration_min: float
    lap_time_multiplier: float = 1.4
    sc_pit_loss_sec: float = 25.0
    pull_pit_into_sc: bool = True


@dataclass
class SafetyCarComparison:
    original: PlanResult
    replanned: PlanResult
    time_delta_min: float = 0.0
    pit_stops_moved: list[str] = field(default_factory=list)
    fuel_saved_liters: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def time_gained(self) -> bool:
        return self.time_delta_min > 0.01


def _find_active_stint(stints: list[Stint], time_min: float) -> Optional[Stint]:
    for stint in stints:
        if stint.start_min <= time_min < stint.end_min:
            return stint
    return None


def _completed_stints_before(stints: list[Stint], time_min: float) -> list[Stint]:
    return [s for s in stints if s.end_min <= time_min + 0.01]


def _pit_times(stints: list[Stint]) -> list[float]:
    if len(stints) <= 1:
        return []
    return [s.end_min for s in stints[:-1]]


def _compare_pit_moves(
    original: PlanResult,
    replanned: PlanResult,
    sc_start: float,
    sc_end: float,
) -> list[str]:
    moved: list[str] = []
    orig_pits = _pit_times(original.stints)
    new_pits = _pit_times(replanned.stints)

    for i, new_pit in enumerate(new_pits):
        in_window = sc_start <= new_pit <= sc_end
        if not in_window:
            continue
        orig_near = None
        for op in orig_pits:
            if abs(op - new_pit) < 8.0:
                orig_near = op
                break
        if orig_near is None or abs(orig_near - new_pit) > 2.0:
            moved.append(
                f"Pit stop moved to {format_duration(new_pit)} "
                f"(inside SC window {format_duration(sc_start)}–"
                f"{format_duration(sc_end)})"
            )
        elif orig_near and not (sc_start <= orig_near <= sc_end):
            moved.append(
                f"Pit stop pulled from {format_duration(orig_near)} into SC "
                f"at {format_duration(new_pit)}"
            )
    return moved


def replan_with_safety_car(
    original: PlanResult,
    sc: SafetyCarConfig,
) -> SafetyCarComparison:
    """
    Re-optimize plan around a Safety Car window.
    Never raises — returns comparison with infeasibilities on failure.
    """
    try:
        config = original.config
        race_end = config.race_duration_min
        deploy = max(0.0, min(sc.deploy_min, race_end))
        duration = max(0.0, sc.duration_min)
        sc_end = min(deploy + duration, race_end)

        if not original.is_feasible:
            return SafetyCarComparison(
                original=original,
                replanned=PlanResult(
                    config=config,
                    infeasibilities=original.infeasibilities,
                ),
                notes=["Cannot replan: original strategy is infeasible."],
            )

        if deploy >= race_end - 0.5:
            return SafetyCarComparison(
                original=original,
                replanned=PlanResult(
                    config=config,
                    stints=original.stints,
                    total_pit_stops=original.total_pit_stops,
                    total_fuel_used_liters=original.total_fuel_used_liters,
                    predicted_laps=original.predicted_laps,
                    time_margin_at_flag_min=original.time_margin_at_flag_min,
                    warnings=["SC at race end — no remaining time to replan."],
                ),
                notes=["SC deployment at or after chequered flag — plan unchanged."],
            )

        if duration <= 0:
            return SafetyCarComparison(
                original=original,
                replanned=original,
                notes=["SC duration is zero — plan unchanged."],
            )

        completed = _completed_stints_before(original.stints, deploy)
        active = _find_active_stint(original.stints, deploy)

        rotation = _RotationState(config.drivers, config.regulations)
        for stint in completed:
            rotation.record(stint.driver, stint.duration_min)

        resume_min = deploy
        resume_driver = config.drivers[0]

        if active:
            elapsed = deploy - active.start_min
            max_cap = config.regulations.max_stint_for_category(active.driver.category)
            if sc.pull_pit_into_sc:
                target_end = min(sc_end, active.start_min + max_cap)
            else:
                target_end = min(active.end_min, active.start_min + max_cap)
            extended = max(target_end - active.start_min, elapsed)
            extended = min(extended, max_cap)

            laps = laps_for_minutes(
                extended,
                config.base_lap_time_sec,
                active.driver.pace_delta_sec,
                max_laps=active.laps,
            )
            laps = max(laps, 1)
            extended = min(
                minutes_for_laps(
                    laps, config.base_lap_time_sec, active.driver.pace_delta_sec
                ),
                extended,
                max_cap,
            )
            completed = list(completed)
            completed.append(
                Stint(
                    stint_number=active.stint_number,
                    driver=active.driver,
                    start_min=active.start_min,
                    duration_min=extended,
                    laps=laps,
                    fuel_load_liters=active.fuel_load_liters,
                    fuel_used_liters=laps * config.fuel_consumption_per_lap,
                    tyres_new=active.tyres_new,
                    tyre_age_at_start_laps=active.tyre_age_at_start_laps,
                    limiting_factor=active.limiting_factor,
                    notes=f"Extended under SC (+{format_duration(max(0.0, extended - elapsed))})",
                )
            )
            rotation.record(active.driver, extended)
            resume_min = completed[-1].end_min

            pit_loss = (
                sc.sc_pit_loss_sec if sc.pull_pit_into_sc
                else pit_stop_duration_sec(config, True)
            ) / 60.0
            resume_min += pit_loss
            names = [d.name for d in config.drivers]
            idx = names.index(active.driver.name)
            resume_driver = config.drivers[(idx + 1) % len(config.drivers)]
        elif completed:
            last = completed[-1]
            names = [d.name for d in config.drivers]
            idx = names.index(last.driver.name)
            resume_driver = config.drivers[(idx + 1) % len(config.drivers)]
            if sc.pull_pit_into_sc:
                resume_min = max(deploy, sc_end - 1.0) + sc.sc_pit_loss_sec / 60.0
            else:
                resume_min = deploy + pit_stop_duration_sec(config, True) / 60.0

        if resume_min >= race_end:
            partial = PlanResult(
                config=config,
                stints=completed,
                total_pit_stops=max(0, len(completed) - 1),
                total_fuel_used_liters=sum(s.fuel_used_liters for s in completed),
                predicted_laps=sum(s.laps for s in completed),
                time_margin_at_flag_min=max(race_end - resume_min, 0.0),
                warnings=["SC leaves no remaining race time after pit stop."],
            )
            return SafetyCarComparison(
                original=original,
                replanned=partial,
                notes=["Replan truncated — race ends during SC sequence."],
            )

        sc_config = RaceConfig.from_dict(config.to_dict())
        if sc.pull_pit_into_sc:
            sc_config.pit_stop_time_loss_sec = sc.sc_pit_loss_sec

        rotation.set_current(resume_driver)
        remainder = _build_plan_internal(
            sc_config,
            start_min=resume_min,
            race_end_min=race_end,
            stint_start_number=len(completed) + 1,
            preserve_rotation=True,
            rotation=rotation,
        )

        merged_stints = list(completed)
        for stint in remainder.stints:
            stint.notes = ("SC re-plan | " + stint.notes).strip(" |")
            merged_stints.append(stint)

        margin = max(race_end - (merged_stints[-1].end_min if merged_stints else resume_min), 0.0)
        replanned = PlanResult(
            config=sc_config,
            stints=merged_stints,
            total_pit_stops=max(0, len(merged_stints) - 1),
            total_fuel_used_liters=sum(s.fuel_used_liters for s in merged_stints),
            predicted_laps=sum(s.laps for s in merged_stints),
            time_margin_at_flag_min=margin,
            warnings=[f"Safety Car re-plan from {format_duration(deploy)}"],
        )
        if sc.lap_time_multiplier > 1.0:
            replanned.warnings.append(
                f"SC pace multiplier ×{sc.lap_time_multiplier:.2f} noted; "
                "remainder planned at green-flag pace."
            )

        for reason in preflight_infeasibility_checks(config, replanned.driver_totals()):
            replanned.infeasibilities.append(
                Infeasibility(
                    code="post_sc_regulation",
                    message=reason,
                    suggestion="Adjust SC timing or driver regulation limits.",
                )
            )

        fuel_saved = original.total_fuel_used_liters - replanned.total_fuel_used_liters
        time_delta = replanned.time_margin_at_flag_min - original.time_margin_at_flag_min
        pit_moves = _compare_pit_moves(original, replanned, deploy, sc_end)

        notes = [
            f"SC window: {format_duration(deploy)} – {format_duration(sc_end)} "
            f"({duration:.0f} min, pace ×{sc.lap_time_multiplier:.2f})",
        ]
        if sc.pull_pit_into_sc:
            notes.append("Strategy: pit stop pulled into SC window where possible.")
        if pit_moves:
            notes.extend(pit_moves)

        return SafetyCarComparison(
            original=original,
            replanned=replanned,
            time_delta_min=time_delta,
            pit_stops_moved=pit_moves,
            fuel_saved_liters=fuel_saved,
            notes=notes,
        )
    except Exception as exc:
        fallback = compute_plan(original.config)
        return SafetyCarComparison(
            original=original,
            replanned=fallback,
            notes=[f"SC replan failed: {exc}"],
        )