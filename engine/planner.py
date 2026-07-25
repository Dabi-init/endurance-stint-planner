"""Deterministic, auditable stint planning for pre-race strategy work."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from engine.models import (
    Driver,
    Infeasibility,
    PlanResult,
    RaceConfig,
    Stint,
)
from engine.regulations import preflight_infeasibility_checks

PRESETS_DIR = Path(__file__).resolve().parent.parent / "pitwall" / "presets"

PRESET_FILES: dict[str, str] = {
    "6h Endurance": "6h_endurance.json",
    "24h GT3 Endurance": "24h_gt3_endurance.json",
    "4h Sprint Endurance": "4h_sprint_endurance.json",
}

DEFAULT_PRESET = "6h Endurance"


@dataclass(frozen=True)
class PlanOptions:
    """The small set of levers that intentionally distinguishes strategies."""

    name: str = "Balanced"
    reserve_laps: int | None = None
    fuel_save_pct: float = 0.0
    tyre_change_every_stops: int = 1
    target_stint_fraction: float = 1.0
    start_driver_id: str | None = None

    def resolved_reserve_laps(self, config: RaceConfig) -> int:
        value = (
            config.regulations.fuel_safety_laps
            if self.reserve_laps is None
            else self.reserve_laps
        )
        return max(int(value), 0)


def list_presets() -> list[str]:
    if not PRESETS_DIR.exists():
        return list(PRESET_FILES.keys())
    known = [
        label
        for label, filename in PRESET_FILES.items()
        if (PRESETS_DIR / filename).exists()
    ]
    extras = sorted(
        path.stem.replace("_", " ")
        for path in PRESETS_DIR.glob("*.json")
        if path.name not in PRESET_FILES.values()
    )
    return known + extras


def load_preset(display_name: str) -> RaceConfig:
    filename = PRESET_FILES.get(display_name)
    if filename:
        path = PRESETS_DIR / filename
    else:
        path = PRESETS_DIR / (display_name.lower().replace(" ", "_") + ".json")
    if not path.exists():
        path = PRESETS_DIR / PRESET_FILES[DEFAULT_PRESET]
    with path.open(encoding="utf-8") as handle:
        return RaceConfig.from_dict(json.load(handle))


def validate_config(
    config: RaceConfig,
    options: PlanOptions | None = None,
) -> list[Infeasibility]:
    """Validate user inputs without raising or silently repairing them."""
    issues: list[Infeasibility] = []
    strategy = options or PlanOptions()
    config.ensure_unique_driver_ids()

    checks: list[tuple[bool, str, str, str]] = [
        (
            config.race_duration_hours > 0,
            "invalid_race_duration",
            "Race duration must be greater than zero.",
            "Set the scheduled duration in hours.",
        ),
        (
            config.base_lap_time_sec > 0,
            "invalid_lap_time",
            "Base lap time must be greater than zero.",
            "Enter a representative green-flag lap time in seconds.",
        ),
        (
            config.fuel_tank_liters > 0,
            "invalid_tank",
            "Fuel tank capacity must be greater than zero.",
            "Enter the usable tank capacity in litres.",
        ),
        (
            config.fuel_consumption_per_lap > 0,
            "invalid_consumption",
            "Fuel consumption per lap must be greater than zero.",
            "Enter measured or assumed consumption in litres per lap.",
        ),
        (
            config.refuel_rate_liters_per_sec > 0,
            "invalid_refuel_rate",
            "Refuel rate must be greater than zero.",
            "Enter the series-specific fuel flow in litres per second.",
        ),
        (
            config.tyre_life_laps > 0,
            "invalid_tyre_life",
            "Tyre life must be at least one lap.",
            "Set a positive tyre-life cap.",
        ),
        (
            config.pit_stop_time_loss_sec >= 0,
            "invalid_pit_loss",
            "Pit-lane transit loss cannot be negative.",
            "Use zero or a measured positive transit loss.",
        ),
        (
            0 <= strategy.fuel_save_pct < 30,
            "invalid_fuel_save",
            "Fuel saving must be between 0% and 30%.",
            "Use a measured fuel-saving target.",
        ),
        (
            0.5 <= strategy.target_stint_fraction <= 1.0,
            "invalid_stint_fraction",
            "Target stint fraction must be between 0.50 and 1.00.",
            "Use 1.00 for full-range stints.",
        ),
        (
            strategy.tyre_change_every_stops >= 1,
            "invalid_tyre_interval",
            "Tyre-change interval must be at least one stop.",
            "Use 1 to change at every stop.",
        ),
    ]
    for passed, code, message, suggestion in checks:
        if not passed:
            issues.append(Infeasibility(code, message, suggestion))

    if not config.drivers:
        issues.append(
            Infeasibility(
                "no_drivers",
                "At least one driver is required.",
                "Add the entered drivers and their categories.",
            )
        )
    else:
        for driver in config.drivers:
            if not driver.name.strip():
                issues.append(
                    Infeasibility(
                        "unnamed_driver",
                        "All drivers must have a display name.",
                        "Enter a name for each driver.",
                    )
                )

    if config.fuel_consumption_per_lap > 0:
        reserve = strategy.resolved_reserve_laps(config) * effective_fuel_consumption(
            config, strategy
        )
        if config.fuel_tank_liters <= reserve:
            issues.append(
                Infeasibility(
                    "tank_too_small",
                    (
                        f"The {config.fuel_tank_liters:.1f} L tank cannot exceed "
                        f"the configured {reserve:.1f} L fuel reserve."
                    ),
                    "Increase tank size, reduce burn, or reduce reserve laps.",
                )
            )

    for reason in preflight_infeasibility_checks(config):
        issues.append(
            Infeasibility(
                "regulation_conflict",
                reason,
                "Adjust the driver roster, race length, or configured rules.",
            )
        )
    return issues


def effective_fuel_consumption(
    config: RaceConfig,
    options: PlanOptions | None = None,
) -> float:
    saving = max((options or PlanOptions()).fuel_save_pct, 0.0) / 100.0
    return max(config.fuel_consumption_per_lap * (1.0 - saving), 0.0)


def fuel_limited_laps(
    config: RaceConfig,
    options: PlanOptions | None = None,
) -> int:
    strategy = options or PlanOptions()
    burn = effective_fuel_consumption(config, strategy)
    reserve = strategy.resolved_reserve_laps(config) * burn
    usable = config.fuel_tank_liters - reserve
    if usable <= 0 or burn <= 0:
        return 0
    return max(math.floor((usable + 1e-9) / burn), 0)


def minutes_for_laps(
    laps: int,
    base_lap_time_sec: float,
    pace_delta_sec: float = 0.0,
) -> float:
    if laps <= 0:
        return 0.0
    return laps * max(base_lap_time_sec + pace_delta_sec, 1.0) / 60.0


def laps_for_minutes(
    minutes: float,
    base_lap_time_sec: float,
    pace_delta_sec: float = 0.0,
    max_laps: int | None = None,
) -> int:
    if minutes <= 0:
        return 0
    lap_time_sec = max(base_lap_time_sec + pace_delta_sec, 1.0)
    laps = math.floor((minutes * 60.0 + 1e-9) / lap_time_sec)
    if max_laps is not None:
        laps = min(laps, max_laps)
    return max(laps, 0)


def pit_stop_duration_sec(
    config: RaceConfig,
    change_tyres: bool,
    fuel_added_liters: float | None = None,
    change_driver: bool = True,
) -> float:
    """Return pit-lane transit plus declared parallel/sequential service."""
    transit = max(config.pit_stop_time_loss_sec, 0.0)
    fuel_amount = (
        config.fuel_tank_liters
        if fuel_added_liters is None
        else max(fuel_added_liters, 0.0)
    )
    refuel = fuel_amount / max(config.refuel_rate_liters_per_sec, 1e-9)
    tyre = max(config.tyre_change_time_sec, 0.0) if change_tyres else 0.0
    driver = max(config.driver_change_time_sec, 0.0) if change_driver else 0.0
    service = (
        max(refuel, tyre, driver)
        if config.services_parallel
        else (refuel + tyre + driver)
    )
    return transit + service


def limiting_factor_label(fuel_laps: int, tyre_laps: int) -> str:
    if fuel_laps <= 0 or tyre_laps <= 0:
        return "Infeasible"
    if fuel_laps < tyre_laps:
        return "Fuel-limited"
    if tyre_laps < fuel_laps:
        return "Tyre-limited"
    return "Fuel/Tyre equal"


class _RotationState:
    """Driver rotation keyed by stable IDs, never display names."""

    def __init__(self, drivers: list[Driver], regulations) -> None:
        self.drivers = drivers
        self.regulations = regulations
        self._index = 0
        self._totals: dict[str, float] = {driver.id: 0.0 for driver in drivers}

    def reset(self) -> None:
        self._index = 0
        self._totals = {driver.id: 0.0 for driver in self.drivers}

    @property
    def current(self) -> Driver:
        return self.drivers[self._index]

    def set_current(self, driver: Driver) -> None:
        ids = [item.id for item in self.drivers]
        if driver.id in ids:
            self._index = ids.index(driver.id)

    def set_current_id(self, driver_id: str | None) -> None:
        ids = [driver.id for driver in self.drivers]
        if driver_id in ids:
            self._index = ids.index(driver_id)

    def record(self, driver: Driver, minutes: float) -> None:
        self._totals[driver.id] = self._totals.get(driver.id, 0.0) + minutes

    def total(self, driver: Driver) -> float:
        return self._totals.get(driver.id, 0.0)

    def remaining_total_capacity(self, driver: Driver) -> float:
        maximum = self.regulations.max_total_drive_min
        if maximum <= 0:
            return math.inf
        return max(maximum - self.total(driver), 0.0)

    def select_next(self, avoid_id: str | None = None) -> Driver | None:
        if not self.drivers:
            return None
        order = [
            (self._index + offset) % len(self.drivers)
            for offset in range(1, len(self.drivers) + 1)
        ]
        eligible = [
            index
            for index in order
            if self.remaining_total_capacity(self.drivers[index]) > 0.5
            and (
                len(self.drivers) == 1
                or not avoid_id
                or self.drivers[index].id != avoid_id
            )
        ]
        if not eligible:
            return None

        deficits: list[tuple[float, int]] = []
        for index in eligible:
            driver = self.drivers[index]
            required = self.regulations.min_drive_for_category(driver.category)
            deficit = max(required - self.total(driver), 0.0)
            deficits.append((deficit, index))
        best_deficit, best_index = max(deficits, key=lambda item: item[0])
        self._index = best_index if best_deficit > 0.5 else eligible[0]
        return self.current


def _driver_lap_time_sec(
    config: RaceConfig,
    driver: Driver,
    options: PlanOptions,
) -> float:
    return driver.lap_time_sec(
        config.base_lap_time_sec,
        fuel_save_pct=options.fuel_save_pct,
        fuel_save_pace_cost_sec_per_pct=config.fuel_save_pace_cost_sec_per_pct,
    )


def _driver_stint_cap_min(
    config: RaceConfig,
    driver: Driver,
    rotation: _RotationState,
) -> float:
    category_cap = config.regulations.max_stint_for_category(driver.category)
    general_cap = config.regulations.max_continuous_stint_min
    caps = [value for value in (category_cap, general_cap) if value > 0]
    continuous = min(caps) if caps else math.inf
    return min(continuous, rotation.remaining_total_capacity(driver))


def _max_stint_laps(
    config: RaceConfig,
    driver: Driver,
    tyre_age_laps: int,
    rotation: _RotationState,
    options: PlanOptions,
) -> tuple[int, str]:
    fuel_laps = fuel_limited_laps(config, options)
    tyre_laps = max(config.tyre_life_laps - tyre_age_laps, 0)
    lap_time_sec = _driver_lap_time_sec(config, driver, options)
    driver_cap = _driver_stint_cap_min(config, driver, rotation)
    driver_laps = (
        max(fuel_laps, tyre_laps)
        if math.isinf(driver_cap)
        else math.floor((driver_cap * 60.0) / lap_time_sec)
    )
    limits = {
        "Fuel-limited": fuel_laps,
        "Tyre-limited": tyre_laps,
        "Driver-limited": driver_laps,
    }
    value = min(limits.values())
    label = next(name for name, laps in limits.items() if laps == value)
    return max(value, 0), label


def _tyre_change_due(
    config: RaceConfig,
    options: PlanOptions,
    stop_number: int,
    tyre_age_after_laps: int,
) -> bool:
    scheduled = stop_number % max(options.tyre_change_every_stops, 1) == 0
    forced_by_rules = config.regulations.change_tyres_every_stop
    forced_by_life = tyre_age_after_laps >= config.tyre_life_laps
    return forced_by_rules or scheduled or forced_by_life


def _planned_laps(
    max_laps: int,
    available_min: float,
    lap_time_sec: float,
    options: PlanOptions,
) -> int:
    clock_laps = math.floor((available_min * 60.0 + 1e-9) / lap_time_sec)
    if clock_laps <= max_laps:
        return max(clock_laps, 0)
    target = math.floor(max_laps * options.target_stint_fraction)
    return max(min(max_laps, target), 1)


def _lookahead_pit(
    config: RaceConfig,
    options: PlanOptions,
    rotation: _RotationState,
    current_driver: Driver,
    current_end_min: float,
    race_end_min: float,
    fuel_remaining: float,
    tyre_age_after: int,
    stop_number: int,
) -> tuple[Driver, bool, int, float, float] | None:
    """Resolve the next stint and its exact fuel add with a small fixed point."""
    next_driver = rotation.select_next(avoid_id=current_driver.id)
    if next_driver is None:
        return None

    change_tyres = _tyre_change_due(config, options, stop_number, tyre_age_after)
    next_tyre_age = 0 if change_tyres else tyre_age_after
    next_max_laps, _ = _max_stint_laps(
        config, next_driver, next_tyre_age, rotation, options
    )
    if next_max_laps <= 0 and not change_tyres:
        change_tyres = True
        next_tyre_age = 0
        next_max_laps, _ = _max_stint_laps(
            config, next_driver, next_tyre_age, rotation, options
        )
    if next_max_laps <= 0:
        return None

    burn = effective_fuel_consumption(config, options)
    reserve = options.resolved_reserve_laps(config) * burn
    change_driver = next_driver.id != current_driver.id
    pit_seconds = pit_stop_duration_sec(
        config,
        change_tyres,
        fuel_added_liters=0.0,
        change_driver=change_driver,
    )
    next_laps = 0
    fuel_added = 0.0

    for _ in range(8):
        available = race_end_min - current_end_min - pit_seconds / 60.0
        candidate = _planned_laps(
            next_max_laps,
            available,
            _driver_lap_time_sec(config, next_driver, options),
            options,
        )
        if candidate <= 0:
            return None
        target_load = min(config.fuel_tank_liters, candidate * burn + reserve)
        candidate_added = max(target_load - fuel_remaining, 0.0)
        candidate_pit = pit_stop_duration_sec(
            config,
            change_tyres,
            fuel_added_liters=candidate_added,
            change_driver=change_driver,
        )
        if (
            candidate == next_laps
            and abs(candidate_added - fuel_added) < 0.01
            and abs(candidate_pit - pit_seconds) < 0.01
        ):
            break
        next_laps = candidate
        fuel_added = candidate_added
        pit_seconds = candidate_pit

    return next_driver, change_tyres, next_tyre_age, fuel_added, pit_seconds


def _build_plan_internal(
    config: RaceConfig,
    options: PlanOptions | None = None,
    start_min: float = 0.0,
    race_end_min: float | None = None,
    stint_start_number: int = 1,
    preserve_rotation: bool = False,
    rotation: _RotationState | None = None,
) -> PlanResult:
    strategy = options or PlanOptions()
    race_end = (
        config.race_duration_min if race_end_min is None else max(race_end_min, 0.0)
    )
    rot = rotation or _RotationState(config.drivers, config.regulations)
    if not preserve_rotation:
        rot.reset()
        rot.set_current_id(strategy.start_driver_id)

    current_driver = rot.current
    current_min = max(start_min, 0.0)
    stint_number = stint_start_number
    tyre_age = 0
    tyre_set = 1
    fuel_at_start: float | None = None
    fuel_added_at_start = 0.0
    pit_stops = 0
    total_pit_time = 0.0
    stints: list[Stint] = []
    burn = effective_fuel_consumption(config, strategy)
    reserve = strategy.resolved_reserve_laps(config) * burn

    while current_min < race_end - 0.01:
        max_laps, limiter = _max_stint_laps(
            config, current_driver, tyre_age, rot, strategy
        )
        lap_time_sec = _driver_lap_time_sec(config, current_driver, strategy)
        laps = _planned_laps(max_laps, race_end - current_min, lap_time_sec, strategy)
        if laps <= 0:
            break

        duration = laps * lap_time_sec / 60.0
        required_load = min(config.fuel_tank_liters, laps * burn + reserve)
        load = required_load if fuel_at_start is None else fuel_at_start
        # Lookahead is deterministic; this guard narrows floating-point drift.
        load = min(max(load, required_load), config.fuel_tank_liters)
        used = laps * burn
        remaining_fuel = max(load - used, 0.0)
        end_min = current_min + duration
        tyre_age_after = tyre_age + laps
        is_clock_final = end_min >= race_end - lap_time_sec / 60.0

        stint = Stint(
            stint_number=stint_number,
            driver=current_driver,
            start_min=current_min,
            duration_min=duration,
            laps=laps,
            fuel_load_liters=load,
            fuel_used_liters=used,
            tyres_new=tyre_age == 0,
            tyre_age_at_start_laps=tyre_age,
            limiting_factor="Race clock" if is_clock_final else limiter,
            notes="Final stint" if is_clock_final else limiter,
            fuel_added_liters=fuel_added_at_start,
            fuel_remaining_liters=remaining_fuel,
            tyre_set=tyre_set,
        )
        stints.append(stint)
        rot.record(current_driver, duration)

        if is_clock_final:
            break

        pit = _lookahead_pit(
            config,
            strategy,
            rot,
            current_driver,
            end_min,
            race_end,
            remaining_fuel,
            tyre_age_after,
            pit_stops + 1,
        )
        if pit is None:
            break
        next_driver, change_tyres, next_tyre_age, fuel_added, pit_seconds = pit
        if end_min + pit_seconds / 60.0 >= race_end - 0.01:
            break

        stint.pit_time_after_sec = pit_seconds
        pit_stops += 1
        total_pit_time += pit_seconds
        current_min = end_min + pit_seconds / 60.0
        current_driver = next_driver
        fuel_at_start = min(remaining_fuel + fuel_added, config.fuel_tank_liters)
        fuel_added_at_start = fuel_added
        tyre_age = next_tyre_age
        if change_tyres:
            tyre_set += 1
        stint_number += 1

    total_laps = sum(stint.laps for stint in stints)
    total_fuel = sum(stint.fuel_used_liters for stint in stints)
    final_end = stints[-1].end_min if stints else current_min
    margin = max(race_end - final_end, 0.0)
    result = PlanResult(
        config=config,
        stints=stints,
        total_pit_stops=pit_stops,
        total_fuel_used_liters=total_fuel,
        predicted_laps=total_laps,
        time_margin_at_flag_min=margin,
        total_pit_time_sec=total_pit_time,
        strategy_name=strategy.name,
        source_summary=config.data_source,
        assumptions=[
            f"{strategy.resolved_reserve_laps(config)} reserve lap(s)",
            f"{strategy.fuel_save_pct:.1f}% fuel save",
            (
                "Pit services run in parallel"
                if config.services_parallel
                else "Pit services run sequentially"
            ),
            (
                "Tyres changed every stop"
                if config.regulations.change_tyres_every_stop
                else (
                    "Tyres scheduled every "
                    f"{strategy.tyre_change_every_stops} stop(s), subject to life"
                )
            ),
        ],
    )

    for reason in preflight_infeasibility_checks(config, result.driver_totals_by_id()):
        result.infeasibilities.append(
            Infeasibility(
                "post_plan_regulation",
                reason,
                "Adjust driver order, limits, or race assumptions.",
            )
        )

    if not stints:
        result.infeasibilities.append(
            Infeasibility(
                "empty_plan",
                "No complete lap fits the configured model.",
                "Check the race clock, fuel range, tyre life, and driver caps.",
            )
        )
    elif (
        margin
        >= min(
            _driver_lap_time_sec(config, driver, strategy) for driver in config.drivers
        )
        / 60.0
    ):
        result.infeasibilities.append(
            Infeasibility(
                "clock_uncovered",
                (
                    f"The plan leaves {margin:.1f} minutes of race clock "
                    "uncovered by a complete stint."
                ),
                "Relax a limiting driver/tyre constraint or revise the rotation.",
            )
        )
    return result


def compute_plan(
    config: RaceConfig,
    options: PlanOptions | None = None,
) -> PlanResult:
    """Compute a full plan; invalid input is returned as structured evidence."""
    strategy = options or PlanOptions()
    try:
        issues = validate_config(config, strategy)
        if issues:
            return PlanResult(
                config=config,
                infeasibilities=issues,
                strategy_name=strategy.name,
                source_summary=config.data_source,
            )
        return _build_plan_internal(config, strategy)
    except Exception as exc:
        return PlanResult(
            config=config,
            strategy_name=strategy.name,
            source_summary=config.data_source,
            infeasibilities=[
                Infeasibility(
                    "internal_error",
                    f"Planning failed safely: {exc}",
                    "Review inputs or attach the exported model report to an issue.",
                )
            ],
        )


def compute_plan_with_tyre_life(
    config: RaceConfig,
    tyre_life_laps: int,
) -> PlanResult:
    """Compatibility helper for tyre-life what-if analysis."""
    adjusted = RaceConfig.from_dict(config.to_dict())
    adjusted.tyre_life_laps = max(int(tyre_life_laps), 1)
    return compute_plan(adjusted)
