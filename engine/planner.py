"""Pure stint planning logic — fuel, tyre, and driver rotation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from engine.models import (
    Driver,
    DriverCategory,
    Infeasibility,
    PlanResult,
    RaceConfig,
    Stint,
    format_duration,
)
from engine.regulations import preflight_infeasibility_checks

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

PRESET_FILES: dict[str, str] = {
    "6h Endurance": "6h_endurance.json",
    "24h GT3 Endurance": "24h_gt3_endurance.json",
    "4h Sprint Endurance": "4h_sprint_endurance.json",
}

DEFAULT_PRESET = "6h Endurance"


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return list(PRESET_FILES.keys())
    known = [label for label, fname in PRESET_FILES.items() if (PRESETS_DIR / fname).exists()]
    extras = sorted(
        p.stem.replace("_", " ")
        for p in PRESETS_DIR.glob("*.json")
        if p.name not in PRESET_FILES.values()
    )
    return known + extras


def load_preset(display_name: str) -> RaceConfig:
    fname = PRESET_FILES.get(display_name)
    if fname:
        path = PRESETS_DIR / fname
    else:
        path = PRESETS_DIR / (display_name.lower().replace(" ", "_") + ".json")
    if not path.exists():
        path = PRESETS_DIR / PRESET_FILES[DEFAULT_PRESET]
    with path.open(encoding="utf-8") as fh:
        return RaceConfig.from_dict(json.load(fh))


def _safe_float(value: float, default: float = 0.0) -> float:
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def validate_config(config: RaceConfig) -> list[Infeasibility]:
    """Validate inputs; never raises."""
    issues: list[Infeasibility] = []

    if config.race_duration_hours <= 0:
        issues.append(
            Infeasibility(
                code="invalid_race_duration",
                message="Race duration must be greater than zero.",
                suggestion="Set race duration to at least 0.5 hours.",
            )
        )

    if config.base_lap_time_sec <= 0:
        issues.append(
            Infeasibility(
                code="invalid_lap_time",
                message="Base lap time must be greater than zero.",
                suggestion="Enter a realistic lap time (e.g. 120 seconds).",
            )
        )

    if config.fuel_tank_liters <= 0:
        issues.append(
            Infeasibility(
                code="invalid_tank",
                message="Fuel tank capacity must be greater than zero.",
                suggestion="Set tank capacity to a positive value (e.g. 100 L).",
            )
        )

    if config.fuel_consumption_per_lap <= 0:
        issues.append(
            Infeasibility(
                code="invalid_consumption",
                message="Fuel consumption per lap must be greater than zero.",
                suggestion="Set consumption to a positive value (e.g. 2.9 L/lap).",
            )
        )

    safety_reserve = (
        config.regulations.fuel_safety_laps * config.fuel_consumption_per_lap
    )
    if config.fuel_tank_liters <= safety_reserve:
        issues.append(
            Infeasibility(
                code="tank_too_small",
                message=(
                    f"Fuel tank ({config.fuel_tank_liters:.1f} L) cannot cover "
                    f"{config.regulations.fuel_safety_laps} safety lap(s) at "
                    f"{config.fuel_consumption_per_lap:.2f} L/lap."
                ),
                suggestion="Increase tank size or reduce safety laps / consumption.",
            )
        )

    if config.tyre_life_laps <= 0:
        issues.append(
            Infeasibility(
                code="invalid_tyre_life",
                message="Tyre life must be at least one lap.",
                suggestion="Set tyre life to a realistic stint cap (e.g. 28 laps).",
            )
        )

    if config.refuel_rate_liters_per_sec <= 0:
        issues.append(
            Infeasibility(
                code="invalid_refuel_rate",
                message="Refuel rate must be greater than zero.",
                suggestion="Use a positive refuel rate (e.g. 2.5 L/s).",
            )
        )

    if not config.drivers:
        issues.append(
            Infeasibility(
                code="no_drivers",
                message="At least one driver is required.",
                suggestion="Add drivers in the sidebar.",
            )
        )

    for driver in config.drivers:
        if not driver.name.strip():
            issues.append(
                Infeasibility(
                    code="unnamed_driver",
                    message="All drivers must have a name.",
                    suggestion="Enter a name for each driver.",
                )
            )

    for reason in preflight_infeasibility_checks(config):
        issues.append(
            Infeasibility(
                code="regulation_conflict",
                message=reason,
                suggestion="Adjust driver count, race length, or regulation limits.",
            )
        )

    return issues


def fuel_limited_laps(config: RaceConfig) -> int:
    usable = config.fuel_tank_liters - (
        config.regulations.fuel_safety_laps * config.fuel_consumption_per_lap
    )
    if usable <= 0 or config.fuel_consumption_per_lap <= 0:
        return 0
    return int(math.floor(usable / config.fuel_consumption_per_lap))


def minutes_for_laps(
    laps: int,
    base_lap_time_sec: float,
    pace_delta_sec: float = 0.0,
) -> float:
    if laps <= 0:
        return 0.0
    lap_min = max(base_lap_time_sec + pace_delta_sec, 1.0) / 60.0
    return laps * lap_min


def laps_for_minutes(
    minutes: float,
    base_lap_time_sec: float,
    pace_delta_sec: float = 0.0,
    max_laps: Optional[int] = None,
) -> int:
    if minutes <= 0:
        return 0
    lap_min = max(base_lap_time_sec + pace_delta_sec, 1.0) / 60.0
    if lap_min <= 0:
        return 0
    laps = int(math.floor(minutes / lap_min))
    if max_laps is not None:
        laps = min(laps, max_laps)
    return max(laps, 0)


def pit_stop_duration_sec(config: RaceConfig, change_tyres: bool) -> float:
    total = max(config.pit_stop_time_loss_sec, 0.0)
    if change_tyres and config.regulations.change_tyres_every_stop:
        total += max(config.tyre_change_time_sec, 0.0)
    return total


def limiting_factor_label(fuel_laps: int, tyre_laps: int) -> str:
    if fuel_laps <= 0 or tyre_laps <= 0:
        return "Infeasible"
    if fuel_laps < tyre_laps:
        return "Fuel-limited"
    if tyre_laps < fuel_laps:
        return "Tyre-limited"
    return "Fuel/Tyre equal"


class _RotationState:
    def __init__(self, drivers: list[Driver], regulations):
        self.drivers = drivers
        self.regulations = regulations
        self._index = 0
        self._totals: dict[str, float] = {d.name: 0.0 for d in drivers}

    def reset(self) -> None:
        self._index = 0
        self._totals = {d.name: 0.0 for d in self.drivers}

    @property
    def current(self) -> Driver:
        return self.drivers[self._index]

    def set_current(self, driver: Driver) -> None:
        names = [d.name for d in self.drivers]
        if driver.name in names:
            self._index = names.index(driver.name)

    def record(self, driver: Driver, minutes: float) -> None:
        self._totals[driver.name] = self._totals.get(driver.name, 0.0) + minutes

    def _stint_cap_min(
        self,
        driver: Driver,
        max_stint_min: float,
        remaining_min: float,
    ) -> float:
        cap = self.regulations.max_stint_for_category(driver.category)
        if cap <= 0:
            cap = max_stint_min
        return min(cap, max_stint_min, remaining_min)

    def select_next(
        self,
        remaining_min: float,
        max_stint_min: float,
        avoid_name: Optional[str] = None,
    ) -> Driver:
        if len(self.drivers) == 1:
            return self.drivers[0]

        n = len(self.drivers)
        rotation_order = [(self._index + offset) % n for offset in range(1, n + 1)]

        deficit_idx: Optional[int] = None
        deficit_score = -1.0
        for idx in rotation_order:
            driver = self.drivers[idx]
            if avoid_name and driver.name == avoid_name:
                continue
            cap = self._stint_cap_min(driver, max_stint_min, remaining_min)
            if cap <= 0:
                continue
            min_req = self.regulations.min_drive_for_category(driver.category)
            deficit = max(0.0, min_req - self._totals.get(driver.name, 0.0))
            if deficit > 0 and deficit > deficit_score:
                deficit_score = deficit
                deficit_idx = idx

        avg_stint = max(max_stint_min * 0.6, 30.0)
        stints_left = max(1, int(math.ceil(remaining_min / avg_stint)))
        if (
            deficit_idx is not None
            and deficit_score > 0
            and stints_left <= len(self.drivers) + 1
        ):
            self._index = deficit_idx
            return self.current

        for idx in rotation_order:
            driver = self.drivers[idx]
            if avoid_name and driver.name == avoid_name:
                continue
            if self._stint_cap_min(driver, max_stint_min, remaining_min) > 0:
                self._index = idx
                return self.current

        return self.current


def _compute_stint_geometry(
    config: RaceConfig,
    driver: Driver,
    remaining_min: float,
    tyre_age_laps: int,
) -> tuple[int, float, str]:
    fuel_laps = fuel_limited_laps(config)
    tyre_laps = max(config.tyre_life_laps - tyre_age_laps, 0)
    driver_cap = config.regulations.max_stint_for_category(driver.category)

    fuel_min = minutes_for_laps(
        fuel_laps, config.base_lap_time_sec, driver.pace_delta_sec
    )
    tyre_min = minutes_for_laps(
        tyre_laps, config.base_lap_time_sec, driver.pace_delta_sec
    )

    cap_min = min(fuel_min, tyre_min, driver_cap, remaining_min)
    if cap_min <= 0:
        return 0, 0.0, limiting_factor_label(fuel_laps, tyre_laps)

    pit_min = pit_stop_duration_sec(config, change_tyres=True) / 60.0
    is_final = remaining_min <= cap_min + pit_min + 0.5

    if is_final:
        laps = laps_for_minutes(
            remaining_min,
            config.base_lap_time_sec,
            driver.pace_delta_sec,
            max_laps=min(fuel_laps, tyre_laps) if min(fuel_laps, tyre_laps) > 0 else None,
        )
        laps = max(laps, 1) if remaining_min > 0.5 else 0
        laps = min(laps, fuel_laps, tyre_laps) if fuel_laps and tyre_laps else laps
        duration = min(
            minutes_for_laps(laps, config.base_lap_time_sec, driver.pace_delta_sec),
            remaining_min,
        )
    else:
        laps = laps_for_minutes(
            cap_min,
            config.base_lap_time_sec,
            driver.pace_delta_sec,
            max_laps=min(fuel_laps, tyre_laps),
        )
        duration = minutes_for_laps(
            laps, config.base_lap_time_sec, driver.pace_delta_sec
        )
        duration = min(duration, remaining_min)

    limit = limiting_factor_label(fuel_laps, max(tyre_laps, 1))
    return max(laps, 0), max(duration, 0.0), limit


def _build_plan_internal(
    config: RaceConfig,
    start_min: float = 0.0,
    race_end_min: Optional[float] = None,
    stint_start_number: int = 1,
    preserve_rotation: bool = False,
    rotation: Optional[_RotationState] = None,
) -> PlanResult:
    race_end = race_end_min if race_end_min is not None else config.race_duration_min
    rot = rotation or _RotationState(config.drivers, config.regulations)
    if not preserve_rotation:
        rot.reset()

    stints: list[Stint] = []
    current_min = max(start_min, 0.0)
    stint_number = stint_start_number
    pit_stops = 0
    total_fuel = 0.0
    total_laps = 0
    last_driver: Optional[str] = None
    tyre_age = 0

    fuel_laps = fuel_limited_laps(config)

    while current_min < race_end - 0.25:
        remaining = race_end - current_min
        if stints:
            rot.select_next(remaining, config.regulations.max_continuous_stint_min, last_driver)
        driver = rot.current

        laps, duration, limit = _compute_stint_geometry(
            config, driver, remaining, tyre_age
        )
        if laps <= 0 or duration <= 0:
            break

        min_req = config.regulations.min_drive_for_category(driver.category)
        driven_so_far = rot._totals.get(driver.name, 0.0)
        deficit_after = max(0.0, min_req - driven_so_far - duration)
        if deficit_after > 0.5 and min_req > 0:
            driver_cap = config.regulations.max_stint_for_category(driver.category)
            extend_room = min(
                max(driver_cap - duration, 0.0),
                max(remaining - duration, 0.0),
            )
            fuel_laps_cap = fuel_limited_laps(config)
            tyre_laps_cap = max(config.tyre_life_laps - tyre_age, 0)
            max_laps_now = laps_for_minutes(
                duration + extend_room,
                config.base_lap_time_sec,
                driver.pace_delta_sec,
                max_laps=min(fuel_laps_cap, tyre_laps_cap) if fuel_laps_cap and tyre_laps_cap else None,
            )
            target_laps = laps_for_minutes(
                duration + min(deficit_after, extend_room),
                config.base_lap_time_sec,
                driver.pace_delta_sec,
                max_laps=min(fuel_laps_cap, tyre_laps_cap) if fuel_laps_cap and tyre_laps_cap else None,
            )
            if target_laps > laps:
                laps = target_laps
                duration = min(
                    minutes_for_laps(laps, config.base_lap_time_sec, driver.pace_delta_sec),
                    remaining,
                    driver_cap if driver_cap > 0 else remaining,
                )

        fuel_used = laps * config.fuel_consumption_per_lap
        is_final = remaining <= duration + (
            pit_stop_duration_sec(config, change_tyres=True) / 60.0
        ) + 0.5

        notes = []
        if is_final:
            notes.append("Final stint")
        if limit:
            notes.append(limit)

        stints.append(
            Stint(
                stint_number=stint_number,
                driver=driver,
                start_min=current_min,
                duration_min=duration,
                laps=laps,
                fuel_load_liters=config.fuel_tank_liters,
                fuel_used_liters=fuel_used,
                tyres_new=tyre_age == 0,
                tyre_age_at_start_laps=tyre_age,
                limiting_factor=limit,
                notes=" | ".join(notes),
            )
        )
        rot.record(driver, duration)
        total_fuel += fuel_used
        total_laps += laps
        last_driver = driver.name
        current_min += duration
        stint_number += 1

        if is_final:
            break

        current_min += pit_stop_duration_sec(config, change_tyres=True) / 60.0
        pit_stops += 1
        tyre_age = 0

    margin = max(race_end - current_min, 0.0)

    result = PlanResult(
        config=config,
        stints=stints,
        total_pit_stops=pit_stops,
        total_fuel_used_liters=total_fuel,
        predicted_laps=total_laps,
        time_margin_at_flag_min=margin,
    )

    postflight = preflight_infeasibility_checks(config, result.driver_totals())
    for reason in postflight:
        result.infeasibilities.append(
            Infeasibility(
                code="post_plan_regulation",
                message=reason,
                suggestion="Adjust driver rotation or regulation minimums.",
            )
        )

    if not stints:
        result.infeasibilities.append(
            Infeasibility(
                code="empty_plan",
                message="Could not build any stints with the current parameters.",
                suggestion=(
                    "Check fuel range, tyre life, and race duration — "
                    "the race may be shorter than one stint."
                ),
            )
        )
    elif margin < -0.5:
        result.infeasibilities.append(
            Infeasibility(
                code="overrun",
                message=(
                    f"Plan exceeds race duration by {format_duration(-margin)}."
                ),
                suggestion="Reduce stint lengths or increase race duration.",
            )
        )

    if fuel_laps <= 0:
        result.infeasibilities.append(
            Infeasibility(
                code="no_fuel_range",
                message="Fuel geometry yields zero laps per stint.",
                suggestion="Increase tank size or reduce consumption / safety laps.",
            )
        )

    return result


def compute_plan(config: RaceConfig) -> PlanResult:
    """
    Compute a full stint plan. Never raises — returns Infeasibility reasons
    inside PlanResult on invalid input or impossible strategy.
    """
    try:
        issues = validate_config(config)
        if issues:
            return PlanResult(config=config, infeasibilities=issues)

        return _build_plan_internal(config)
    except Exception as exc:
        return PlanResult(
            config=config,
            infeasibilities=[
                Infeasibility(
                    code="internal_error",
                    message=f"Planning failed: {exc}",
                    suggestion="Review inputs and try again.",
                )
            ],
        )


def compute_plan_with_tyre_life(
    config: RaceConfig,
    tyre_life_laps: int,
) -> PlanResult:
    """Recompute plan with overridden tyre life (for live what-if slider)."""
    try:
        adjusted = RaceConfig.from_dict(config.to_dict())
        adjusted.tyre_life_laps = max(int(tyre_life_laps), 1)
        return compute_plan(adjusted)
    except Exception as exc:
        return PlanResult(
            config=config,
            infeasibilities=[
                Infeasibility(
                    code="tyre_override_error",
                    message=str(exc),
                    suggestion="Reset tyre life to a positive value.",
                )
            ],
        )