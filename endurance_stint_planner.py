#!/usr/bin/env python3
"""
Endurance Race Stint Planner
============================

Strategy planning tool for endurance sportscar racing (Fun Cup, Lamera Cup,
ELMS). Computes fuel- and tyre-limited stints, series-specific driver
regulations, mandatory pit windows, gap simulation, and Safety Car re-plans.

Author: Sreenath R. — ESSEC MIM 2026
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def format_duration(minutes: float) -> str:
    """Format minutes as H:MM:SS for pit-wall readability."""
    total_seconds = int(round(minutes * 60))
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def parse_lap_time(lap_time_str: str) -> float:
    """Parse lap time: '125', '2:05', or '1:42.500' → seconds."""
    lap_time_str = lap_time_str.strip()
    if ":" not in lap_time_str:
        return float(lap_time_str)

    parts = lap_time_str.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise ValueError(f"Invalid lap time format: {lap_time_str}")


def parse_optional_float(value: str, default: float) -> float:
    value = value.strip()
    return float(value) if value else default


# ---------------------------------------------------------------------------
# Series regulations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MandatoryPitWindow:
    """Regulated refuelling window (race minutes from green flag)."""
    open_min: float
    close_min: float

    def contains(self, race_min: float) -> bool:
        return self.open_min <= race_min <= self.close_min


@dataclass
class SeriesRegulations:
    """
    Championship-specific sporting rules applied to stint planning.

    Fun Cup rules sourced from 2024 Fun Cup Endurance Championship Sporting
    Regulations (BRSCC / Motorsport UK), sections 2.4.3–2.4.8.
    ELMS LMGT3 rules follow FIA WEC driver classification limits.
    """
    series_id: str
    name: str
    regulation_ref: str
    min_drivers: int = 2
    # Fun Cup 2.4.3: no driver may exceed 2× combined drive of all others.
    max_drive_vs_others_ratio: Optional[float] = None
    bronze_max_stint_min: Optional[float] = None
    bronze_min_stint_min: Optional[float] = None
    silver_max_stint_min: Optional[float] = None
    pro_max_stint_min: Optional[float] = None
    bronze_min_drive_min: Optional[float] = None
    bronze_min_drive_pct: Optional[float] = None
    mandatory_pit_windows: list[MandatoryPitWindow] = field(default_factory=list)
    min_mandatory_stops: int = 0

    def max_stint_for_category(self, category: "DriverCategory") -> Optional[float]:
        if category == DriverCategory.BRONZE:
            return self.bronze_max_stint_min
        if category == DriverCategory.SILVER:
            return self.silver_max_stint_min
        if category == DriverCategory.PRO:
            return self.pro_max_stint_min
        return None

    def min_stint_for_category(self, category: "DriverCategory") -> Optional[float]:
        if category == DriverCategory.BRONZE:
            return self.bronze_min_stint_min
        return None

    def min_drive_for_driver(
        self, driver: "Driver", race_duration_min: float
    ) -> float:
        """Resolve minimum total drive from explicit value or percentage rule."""
        if driver.min_total_drive_min > 0:
            return driver.min_total_drive_min
        if (
            driver.category == DriverCategory.BRONZE
            and self.bronze_min_drive_min
        ):
            return self.bronze_min_drive_min
        if (
            driver.category == DriverCategory.BRONZE
            and self.bronze_min_drive_pct
        ):
            return race_duration_min * self.bronze_min_drive_pct
        if self.max_drive_vs_others_ratio and self.min_drivers == 2:
            # Balance rule ⇒ each of two drivers must do at least ~33% of race.
            return race_duration_min / 3.0
        return 0.0

    def max_drive_for_driver(
        self,
        driver: "Driver",
        other_drive_min: float,
    ) -> Optional[float]:
        """Fun Cup balance cap: no driver > 2× others combined."""
        if self.max_drive_vs_others_ratio and other_drive_min > 0:
            return self.max_drive_vs_others_ratio * other_drive_min
        return None

    def windows_for_duration(self, race_duration_min: float) -> list[MandatoryPitWindow]:
        return [w for w in self.mandatory_pit_windows if w.close_min <= race_duration_min + 1]


def fun_cup_gt4_regulations() -> SeriesRegulations:
    """Fun Cup 4h — mandatory refuelling windows and driver-balance rule."""
    return SeriesRegulations(
        series_id="fun-cup-gt4",
        name="Fun Cup Endurance Championship (GT4)",
        regulation_ref=(
            "2024 Fun Cup Sporting Regulations §2.4.3 (driver balance), "
            "§2.4.4 (mandatory refuelling windows)"
        ),
        min_drivers=2,
        max_drive_vs_others_ratio=2.0,
        mandatory_pit_windows=[
            MandatoryPitWindow(40, 50),
            MandatoryPitWindow(80, 90),
            MandatoryPitWindow(120, 130),
            MandatoryPitWindow(160, 170),
            MandatoryPitWindow(200, 210),
        ],
        min_mandatory_stops=5,
    )


def fun_cup_validation_regulations() -> SeriesRegulations:
    """
    Validation case study regs — driver balance only.

    Fun Cup 8h mandatory window schedule is set per-event in Supplementary
    Regulations; not published in the 2024 championship handbook excerpt.
    """
    return SeriesRegulations(
        series_id="fun-cup-validation",
        name="Fun Cup (validation — balance rule only)",
        regulation_ref=(
            "2024 Fun Cup §2.4.3 driver balance; "
            "8h refuelling windows omitted (event SR not in handbook)"
        ),
        min_drivers=2,
        max_drive_vs_others_ratio=2.0,
    )


def elms_lmgt3_regulations() -> SeriesRegulations:
    """ELMS LMGT3 — FIA Bronze stint caps and minimum drive."""
    return SeriesRegulations(
        series_id="elms-lmgt3",
        name="ELMS LMGT3",
        regulation_ref="FIA WEC / ELMS LMGT3 driver classification (Bronze limits)",
        min_drivers=3,
        bronze_max_stint_min=65.0,
        bronze_min_stint_min=45.0,
        silver_max_stint_min=90.0,
        pro_max_stint_min=120.0,
        bronze_min_drive_min=120.0,  # 2h minimum in 6h race
        bronze_min_drive_pct=0.333,
    )


def wec_hypercar_regulations() -> SeriesRegulations:
    """WEC Hypercar — simplified Bronze limits (energy not modelled)."""
    return SeriesRegulations(
        series_id="wec-hypercar",
        name="WEC Hypercar",
        regulation_ref="FIA WEC driver classification (Bronze limits)",
        min_drivers=3,
        bronze_max_stint_min=65.0,
        bronze_min_stint_min=45.0,
        pro_max_stint_min=120.0,
        bronze_min_drive_min=120.0,
        bronze_min_drive_pct=0.333,
    )


# ---------------------------------------------------------------------------
# Tyre model
# ---------------------------------------------------------------------------

class TyreCompound(Enum):
    """Tyre compound identifiers."""
    GTR2 = "GTR2"       # Fun Cup mandatory Giti GTR2
    HARD = "HARD"
    MEDIUM = "MEDIUM"
    SOFT = "SOFT"


@dataclass(frozen=True)
class TyreProfile:
    """
    Simple degradation model.

    Lap time increases linearly by deg_per_lap_sec from a fresh lap.
    max_laps: recommended stint cap before cliff.
    cliff_factor: extra deg multiplier after cliff_lap.
    """
    compound: TyreCompound
    base_pace_delta_sec: float = 0.0
    max_laps: int = 22
    deg_per_lap_sec: float = 0.08
    cliff_lap: int = 18
    cliff_factor: float = 2.5

    def lap_time_at_lap(self, base_lap_sec: float, lap_number: int) -> float:
        if lap_number <= 0:
            return base_lap_sec + self.base_pace_delta_sec
        deg = self.deg_per_lap_sec
        if lap_number > self.cliff_lap:
            deg *= self.cliff_factor
        return base_lap_sec + self.base_pace_delta_sec + deg * lap_number

    def remaining_grip_pct(self, laps_completed: int) -> float:
        """100% = fresh, 0% = at recommended max stint."""
        if self.max_laps <= 0:
            return 0.0
        return max(0.0, 100.0 * (1.0 - laps_completed / self.max_laps))


TYRE_PROFILES: dict[TyreCompound, TyreProfile] = {
    TyreCompound.GTR2: TyreProfile(
        compound=TyreCompound.GTR2,
        max_laps=20,
        deg_per_lap_sec=0.10,
        cliff_lap=16,
    ),
    TyreCompound.HARD: TyreProfile(
        compound=TyreCompound.HARD,
        base_pace_delta_sec=0.6,
        max_laps=28,
        deg_per_lap_sec=0.05,
        cliff_lap=24,
    ),
    TyreCompound.MEDIUM: TyreProfile(
        compound=TyreCompound.MEDIUM,
        base_pace_delta_sec=0.0,
        max_laps=22,
        deg_per_lap_sec=0.08,
        cliff_lap=18,
    ),
    TyreCompound.SOFT: TyreProfile(
        compound=TyreCompound.SOFT,
        base_pace_delta_sec=-0.4,
        max_laps=16,
        deg_per_lap_sec=0.12,
        cliff_lap=12,
    ),
}


class TyreCalculator:
    """Tyre-limited stint geometry alongside fuel."""

    def __init__(self, profile: TyreProfile, base_lap_sec: float):
        self.profile = profile
        self.base_lap_sec = base_lap_sec

    def max_stint_laps(self) -> int:
        return self.profile.max_laps

    def max_stint_minutes(self) -> float:
        total_sec = sum(
            self.profile.lap_time_at_lap(self.base_lap_sec, lap)
            for lap in range(1, self.profile.max_laps + 1)
        )
        return total_sec / 60.0

    def avg_lap_time_min(self, laps: int) -> float:
        if laps <= 0:
            return self.base_lap_sec / 60.0
        total = sum(
            self.profile.lap_time_at_lap(self.base_lap_sec, lap)
            for lap in range(1, laps + 1)
        )
        return total / laps / 60.0

    def minutes_for_laps(self, laps: int) -> float:
        if laps <= 0:
            return 0.0
        total_sec = sum(
            self.profile.lap_time_at_lap(self.base_lap_sec, lap)
            for lap in range(1, laps + 1)
        )
        return total_sec / 60.0

    def laps_for_minutes(self, minutes: float) -> int:
        if minutes <= 0:
            return 0
        elapsed = 0.0
        lap = 0
        while lap < self.profile.max_laps:
            lap += 1
            elapsed += self.profile.lap_time_at_lap(self.base_lap_sec, lap) / 60.0
            if elapsed > minutes:
                return max(lap - 1, 0)
        return lap

    def limiting_factor(self, fuel_laps: int) -> str:
        tyre_laps = self.max_stint_laps()
        if tyre_laps < fuel_laps:
            return "Tyre-limited"
        if fuel_laps < tyre_laps:
            return "Fuel-limited"
        return "Fuel/Tyre equal"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class DriverCategory(Enum):
    PRO = "Pro"
    SILVER = "Silver"
    BRONZE = "Bronze"
    AMATEUR = "Amateur"


@dataclass
class Driver:
    name: str
    category: DriverCategory
    min_stint_min: float = 45.0
    max_stint_min: float = 90.0
    min_total_drive_min: float = 0.0

    def effective_max_stint(
        self, regulations: Optional[SeriesRegulations] = None
    ) -> float:
        cap = self.max_stint_min
        if regulations:
            reg_cap = regulations.max_stint_for_category(self.category)
            if reg_cap is not None:
                cap = min(cap, reg_cap)
        return cap

    def effective_min_stint(
        self, regulations: Optional[SeriesRegulations] = None
    ) -> float:
        if regulations:
            reg_min = regulations.min_stint_for_category(self.category)
            if reg_min is not None:
                return max(self.min_stint_min, reg_min)
        return self.min_stint_min


@dataclass
class RaceConfig:
    race_name: str
    race_duration_min: float
    lap_time_sec: float
    fuel_tank_liters: float
    fuel_per_lap_liters: float
    fuel_safety_laps: int = 1
    pit_loss_sec: float = 45.0
    formation_lap_min: float = 5.0
    series_id: str = "custom"

    @property
    def lap_time_min(self) -> float:
        return self.lap_time_sec / 60.0

    def laps_per_stint(self) -> int:
        usable = self.fuel_tank_liters - (
            self.fuel_safety_laps * self.fuel_per_lap_liters
        )
        if usable <= 0:
            raise ValueError("Fuel tank too small for configured safety margin.")
        return int(math.floor(usable / self.fuel_per_lap_liters))

    def stint_duration_min(self, laps: Optional[int] = None) -> float:
        lap_count = laps if laps is not None else self.laps_per_stint()
        return lap_count * self.lap_time_min


@dataclass
class Stint:
    stint_number: int
    driver: Driver
    start_min: float
    duration_min: float
    laps: int
    fuel_used_liters: float
    tyre_compound: TyreCompound = TyreCompound.MEDIUM
    pit_window_open_min: Optional[float] = None
    pit_window_close_min: Optional[float] = None
    tyre_grip_end_pct: float = 100.0
    limiting_factor: str = ""
    notes: str = ""

    @property
    def end_min(self) -> float:
        return self.start_min + self.duration_min

    def to_dict(self) -> dict:
        return {
            "Stint": self.stint_number,
            "Driver": self.driver.name,
            "Category": self.driver.category.value,
            "Tyre": self.tyre_compound.value,
            "Start": format_duration(self.start_min),
            "End": format_duration(self.end_min),
            "Duration": format_duration(self.duration_min),
            "Laps": self.laps,
            "Fuel (L)": round(self.fuel_used_liters, 1),
            "Grip End %": round(self.tyre_grip_end_pct, 0),
            "Limit": self.limiting_factor or "-",
            "Pit Window Open": (
                format_duration(self.pit_window_open_min)
                if self.pit_window_open_min is not None else "-"
            ),
            "Pit Window Close": (
                format_duration(self.pit_window_close_min)
                if self.pit_window_close_min is not None else "-"
            ),
            "Notes": self.notes,
        }


@dataclass
class StintPlan:
    config: RaceConfig
    stints: list[Stint] = field(default_factory=list)
    total_pit_stops: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    regulations: Optional[SeriesRegulations] = None

    @property
    def race_end_min(self) -> float:
        return self.config.race_duration_min

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([s.to_dict() for s in self.stints])

    def summary(self) -> dict:
        driver_totals: dict[str, float] = {}
        for stint in self.stints:
            driver_totals[stint.driver.name] = (
                driver_totals.get(stint.driver.name, 0.0) + stint.duration_min
            )
        return {
            "race": self.config.race_name,
            "total_stints": len(self.stints),
            "total_pit_stops": self.total_pit_stops,
            "driver_minutes": driver_totals,
            "warnings": self.warnings,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Regulation validation
# ---------------------------------------------------------------------------

class RegulationValidator:
    """Check stint plan against series sporting regulations."""

    def __init__(
        self,
        regulations: SeriesRegulations,
        race_duration_min: float,
    ):
        self.regulations = regulations
        self.race_duration_min = race_duration_min

    def validate(
        self,
        stints: list[Stint],
        drivers: list[Driver],
    ) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        errors: list[str] = []
        totals = drive_totals_from_stints(stints)

        for driver in drivers:
            driven = totals.get(driver.name, 0.0)
            required = self.regulations.min_drive_for_driver(
                driver, self.race_duration_min
            )
            if required > 0 and driven < required - 0.5:
                msg = (
                    f"{driver.name} ({driver.category.value}) short of minimum "
                    f"drive by {format_duration(required - driven)} "
                    f"(driven {format_duration(driven)}, "
                    f"required {format_duration(required)})."
                )
                errors.append(msg)

            other_drive = sum(
                v for n, v in totals.items() if n != driver.name
            )
            max_allowed = self.regulations.max_drive_for_driver(
                driver, other_drive
            )
            if max_allowed and driven > max_allowed + 0.5:
                errors.append(
                    f"{driver.name} exceeds balance rule: drove "
                    f"{format_duration(driven)}, max allowed "
                    f"{format_duration(max_allowed)} "
                    f"(≤{self.regulations.max_drive_vs_others_ratio}× others)."
                )

        for stint in stints:
            reg_max = self.regulations.max_stint_for_category(
                stint.driver.category
            )
            if reg_max and stint.duration_min > reg_max + 0.5:
                errors.append(
                    f"Stint {stint.stint_number}: {stint.driver.name} "
                    f"stint {format_duration(stint.duration_min)} exceeds "
                    f"regulatory max {format_duration(reg_max)}."
                )
            reg_min = self.regulations.min_stint_for_category(
                stint.driver.category
            )
            if (
                reg_min
                and stint.duration_min < reg_min - 0.5
                and stint.stint_number < len(stints)
            ):
                warnings.append(
                    f"Stint {stint.stint_number}: {stint.driver.name} "
                    f"stint {format_duration(stint.duration_min)} below "
                    f"regulatory min {format_duration(reg_min)}."
                )

        self._check_mandatory_windows(stints, warnings, errors)
        return warnings, errors

    def _check_mandatory_windows(
        self,
        stints: list[Stint],
        warnings: list[str],
        errors: list[str],
    ) -> None:
        windows = self.regulations.windows_for_duration(self.race_duration_min)
        if not windows:
            return

        pit_mins = [s.end_min for s in stints[:-1]] if len(stints) > 1 else []
        planner = PitWindowPlanner(
            RaceConfig(
                race_name="",
                race_duration_min=self.race_duration_min,
                lap_time_sec=120,
                fuel_tank_liters=80,
                fuel_per_lap_liters=2.5,
            ),
            self.regulations,
        )
        for index, window in enumerate(windows):
            covered = any(
                planner.window_index_for_pit(p) == index for p in pit_mins
            )
            if not covered:
                errors.append(
                    f"No pit stop within mandatory refuelling window "
                    f"{format_duration(window.open_min)}–"
                    f"{format_duration(window.close_min)}."
                )

        if len(pit_mins) < self.regulations.min_mandatory_stops:
            warnings.append(
                f"Plan has {len(pit_mins)} pit stops; regulations expect "
                f"≥{self.regulations.min_mandatory_stops} mandatory windows."
            )


# ---------------------------------------------------------------------------
# Core planning logic
# ---------------------------------------------------------------------------

class FuelCalculator:
    def __init__(self, config: RaceConfig):
        self.config = config

    def max_stint_laps(self) -> int:
        return self.config.laps_per_stint()

    def max_stint_minutes(self) -> float:
        return self.config.stint_duration_min()

    def fuel_for_laps(self, laps: int) -> float:
        return laps * self.config.fuel_per_lap_liters

    def laps_for_minutes(self, minutes: float) -> int:
        if minutes <= 0:
            return 0
        return int(math.floor(minutes / self.config.lap_time_min))

    def minutes_for_laps(self, laps: int) -> float:
        return laps * self.config.lap_time_min


class DriverRotationManager:
    def __init__(
        self,
        drivers: list[Driver],
        regulations: Optional[SeriesRegulations] = None,
        race_duration_min: float = 240.0,
    ):
        if not drivers:
            raise ValueError("At least one driver is required.")
        self.drivers = drivers
        self.regulations = regulations
        self.race_duration_min = race_duration_min
        self._index = 0
        self._cumulative_drive: dict[str, float] = {d.name: 0.0 for d in drivers}

        for driver in drivers:
            if driver.min_total_drive_min <= 0 and regulations:
                driver.min_total_drive_min = regulations.min_drive_for_driver(
                    driver, race_duration_min
                )

    def reset(self) -> None:
        self._index = 0
        self._cumulative_drive = {d.name: 0.0 for d in self.drivers}

    @property
    def current_driver(self) -> Driver:
        return self.drivers[self._index]

    def set_current_driver(self, driver: Driver) -> None:
        names = [d.name for d in self.drivers]
        if driver.name not in names:
            raise ValueError(f"Driver {driver.name} is not in the lineup.")
        self._index = names.index(driver.name)

    def record_drive(self, driver: Driver, minutes: float) -> None:
        self._cumulative_drive[driver.name] += minutes

    def stint_cap_minutes(
        self,
        driver: Driver,
        fuel_limited_min: float,
        tyre_limited_min: float,
        remaining_race_min: float,
    ) -> float:
        cap = min(
            fuel_limited_min,
            tyre_limited_min,
            driver.effective_max_stint(self.regulations),
            remaining_race_min,
        )
        return max(cap, 0.0)

    def select_priority_driver(
        self,
        fuel_limited_min: float,
        tyre_limited_min: float,
        remaining_race_min: float,
        avoid_driver_name: Optional[str] = None,
    ) -> None:
        next_index = (self._index + 1) % len(self.drivers)
        best_index = next_index
        best_deficit = 0.0

        for index, driver in enumerate(self.drivers):
            if avoid_driver_name and driver.name == avoid_driver_name:
                continue
            driven = self._cumulative_drive[driver.name]
            deficit = max(
                0.0,
                driver.min_total_drive_min - driven,
            )
            stint_cap = self.stint_cap_minutes(
                driver, fuel_limited_min, tyre_limited_min, remaining_race_min
            )
            if stint_cap <= 0:
                continue
            if deficit > best_deficit:
                best_deficit = deficit
                best_index = index

        if remaining_race_min < max(fuel_limited_min, tyre_limited_min) * 1.5:
            for index, driver in enumerate(self.drivers):
                driven = self._cumulative_drive[driver.name]
                deficit = max(0.0, driver.min_total_drive_min - driven)
                stint_cap = self.stint_cap_minutes(
                    driver, fuel_limited_min, tyre_limited_min, remaining_race_min
                )
                if deficit > 0 and stint_cap >= min(
                    driver.effective_min_stint(self.regulations),
                    remaining_race_min,
                ):
                    self._index = index
                    return

        self._index = best_index if best_deficit > 0 else next_index


def validate_driver_totals(
    drivers: list[Driver],
    drive_minutes: dict[str, float],
) -> list[str]:
    warnings = []
    for driver in drivers:
        driven = drive_minutes.get(driver.name, 0.0)
        if driver.min_total_drive_min > 0 and driven < driver.min_total_drive_min:
            shortfall = driver.min_total_drive_min - driven
            warnings.append(
                f"{driver.name} ({driver.category.value}) short of minimum total "
                f"drive by {format_duration(shortfall)}."
            )
    return warnings


def drive_totals_from_stints(stints: list[Stint]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for stint in stints:
        totals[stint.driver.name] = (
            totals.get(stint.driver.name, 0.0) + stint.duration_min
        )
    return totals


def satisfied_windows_from_stints(
    stints: list[Stint],
    regulations: Optional[SeriesRegulations],
    race_duration_min: float,
) -> set[int]:
    """Derive which mandatory refuelling windows are already covered."""
    if not regulations or not stints:
        return set()
    planner = PitWindowPlanner(
        RaceConfig(
            race_name="",
            race_duration_min=race_duration_min,
            lap_time_sec=120,
            fuel_tank_liters=80,
            fuel_per_lap_liters=2.5,
        ),
        regulations,
    )
    satisfied: set[int] = set()
    for stint in stints[:-1]:
        idx = planner.window_index_for_pit(stint.end_min)
        if idx is not None:
            satisfied.add(idx)
    return satisfied


class PitWindowPlanner:
    def __init__(
        self,
        config: RaceConfig,
        regulations: Optional[SeriesRegulations] = None,
    ):
        self.config = config
        self.regulations = regulations

    def compute_window(
        self,
        stint_start_min: float,
        stint_duration_min: float,
        driver: Driver,
        next_mandatory_window: Optional[MandatoryPitWindow] = None,
    ) -> tuple[float, float]:
        stint_end = stint_start_min + stint_duration_min
        window_open = stint_start_min + driver.effective_min_stint(
            self.regulations
        )
        window_close = stint_end
        if next_mandatory_window:
            # Must pit inside the mandatory refuelling window when one applies.
            window_close = min(window_close, next_mandatory_window.close_min)
            window_open = max(window_open, next_mandatory_window.open_min)
        # Keep open/close within the actual stint and ensure open <= close.
        window_open = min(window_open, stint_end)
        window_close = min(window_close, stint_end)
        if window_open > window_close:
            window_open = max(stint_start_min, window_close - 1.0)
        return window_open, window_close

    def next_mandatory_window(
        self,
        current_min: float,
        satisfied: Optional[set[int]] = None,
    ) -> Optional[MandatoryPitWindow]:
        if not self.regulations:
            return None
        satisfied = satisfied or set()
        for index, window in enumerate(
            self.regulations.windows_for_duration(self.config.race_duration_min)
        ):
            if index in satisfied:
                continue
            if current_min <= window.close_min:
                return window
        return None

    def window_index_for_pit(
        self, pit_min: float
    ) -> Optional[int]:
        """Return which mandatory window a pit stop at pit_min satisfies."""
        if not self.regulations:
            return None
        for index, window in enumerate(
            self.regulations.windows_for_duration(self.config.race_duration_min)
        ):
            if window.contains(pit_min):
                return index
        return None

    def minutes_to_window_close(
        self,
        current_min: float,
        satisfied: Optional[set[int]] = None,
    ) -> Optional[float]:
        window = self.next_mandatory_window(current_min, satisfied)
        if window and current_min <= window.close_min:
            return max(window.close_min - current_min, 0.5)
        return None


@dataclass
class PresetBundle:
    config: RaceConfig
    drivers: list[Driver]
    regulations: SeriesRegulations
    default_compounds: list[TyreCompound]


class StintPlanner:
    def __init__(
        self,
        config: RaceConfig,
        drivers: list[Driver],
        regulations: Optional[SeriesRegulations] = None,
        compounds: Optional[list[TyreCompound]] = None,
    ):
        self.config = config
        self.drivers = drivers
        self.regulations = regulations
        self.compounds = compounds or [TyreCompound.MEDIUM]
        self.fuel_calc = FuelCalculator(config)
        self.rotation = DriverRotationManager(
            drivers, regulations, config.race_duration_min
        )
        self.pit_windows = PitWindowPlanner(config, regulations)

    def _tyre_calc_for_stint(self, stint_index: int) -> TyreCalculator:
        compound = self.compounds[stint_index % len(self.compounds)]
        profile = TYRE_PROFILES[compound]
        return TyreCalculator(profile, self.config.lap_time_sec)

    def _compound_for_stint(self, stint_index: int) -> TyreCompound:
        return self.compounds[stint_index % len(self.compounds)]

    def _compute_stint(
        self,
        driver: Driver,
        current_min: float,
        race_end: float,
        fuel_max_laps: int,
        fuel_limited_min: float,
        stint_index: int,
        satisfied_windows: Optional[set[int]] = None,
    ) -> tuple[int, float, bool, str, float]:
        tyre_calc = self._tyre_calc_for_stint(stint_index)
        tyre_max_laps = tyre_calc.max_stint_laps()
        tyre_limited_min = tyre_calc.max_stint_minutes()
        remaining = race_end - current_min

        # Mandatory window may force an earlier stop.
        window_cap_min = self.pit_windows.minutes_to_window_close(
            current_min, satisfied_windows
        )
        if window_cap_min is not None:
            tyre_limited_min = min(tyre_limited_min, window_cap_min)
            fuel_limited_min = min(fuel_limited_min, window_cap_min)

        duration_cap = self.rotation.stint_cap_minutes(
            driver, fuel_limited_min, tyre_limited_min, remaining
        )
        if duration_cap <= 0:
            return 0, 0.0, True, "", 0.0

        pit_loss_min = self.config.pit_loss_sec / 60.0
        effective_limit = min(fuel_limited_min, tyre_limited_min)
        is_final = remaining <= effective_limit + pit_loss_min

        max_laps = min(fuel_max_laps, tyre_max_laps)
        if window_cap_min is not None:
            window_laps = tyre_calc.laps_for_minutes(window_cap_min)
            if window_laps > 0:
                max_laps = min(max_laps, window_laps)

        if is_final:
            laps = max(tyre_calc.laps_for_minutes(remaining), 1)
            laps = min(laps, fuel_max_laps, tyre_max_laps)
            duration = min(tyre_calc.minutes_for_laps(laps), remaining)
        else:
            laps = min(tyre_calc.laps_for_minutes(duration_cap), max_laps)
            duration = tyre_calc.minutes_for_laps(laps)
            min_stint = driver.effective_min_stint(self.regulations)
            if duration < min_stint and not is_final:
                laps = min(tyre_calc.laps_for_minutes(min_stint), max_laps)
                duration = min(tyre_calc.minutes_for_laps(laps), remaining)

        limiting = tyre_calc.limiting_factor(fuel_max_laps)
        grip = tyre_calc.profile.remaining_grip_pct(laps)
        return max(laps, 0), max(duration, 0.0), is_final, limiting, grip

    def build_plan(
        self,
        start_min: float = 0.0,
        race_end_min: Optional[float] = None,
        stint_start_number: int = 1,
        skip_formation: bool = False,
        preserve_rotation: bool = False,
        initial_satisfied_windows: Optional[set[int]] = None,
    ) -> StintPlan:
        if not preserve_rotation:
            self.rotation.reset()

        stints: list[Stint] = []
        stint_number = stint_start_number
        current_min = start_min + (
            0.0 if skip_formation else self.config.formation_lap_min
        )
        race_end = (
            race_end_min if race_end_min is not None
            else start_min + self.config.race_duration_min
        )
        fuel_max_laps = self.fuel_calc.max_stint_laps()
        fuel_limited_min = self.fuel_calc.max_stint_minutes()
        pit_stops = 0
        last_driver_name: Optional[str] = None
        stint_index = 0
        satisfied_windows: set[int] = set(initial_satisfied_windows or [])

        while current_min < race_end - 0.5:
            remaining = race_end - current_min
            if stints:
                self.rotation.select_priority_driver(
                    fuel_limited_min,
                    TyreCalculator(
                        TYRE_PROFILES[self._compound_for_stint(stint_index)],
                        self.config.lap_time_sec,
                    ).max_stint_minutes(),
                    remaining,
                    avoid_driver_name=last_driver_name,
                )
            driver = self.rotation.current_driver
            compound = self._compound_for_stint(stint_index)

            laps, duration, is_final, limiting, grip = self._compute_stint(
                driver, current_min, race_end,
                fuel_max_laps, fuel_limited_min, stint_index,
                satisfied_windows,
            )
            if laps <= 0 or duration <= 0:
                break

            next_window = self.pit_windows.next_mandatory_window(
                current_min, satisfied_windows
            )
            window_open, window_close = self.pit_windows.compute_window(
                current_min, duration, driver, next_window
            )

            note_parts = []
            if is_final:
                note_parts.append("Final stint")
            if limiting:
                note_parts.append(limiting)
            if next_window and window_close <= next_window.close_min + 0.1:
                note_parts.append(
                    f"Mandatory window {format_duration(next_window.open_min)}–"
                    f"{format_duration(next_window.close_min)}"
                )

            stints.append(
                Stint(
                    stint_number=stint_number,
                    driver=driver,
                    start_min=current_min,
                    duration_min=duration,
                    laps=laps,
                    fuel_used_liters=self.fuel_calc.fuel_for_laps(laps),
                    tyre_compound=compound,
                    pit_window_open_min=window_open if not is_final else None,
                    pit_window_close_min=window_close if not is_final else None,
                    tyre_grip_end_pct=grip,
                    limiting_factor=limiting,
                    notes=" | ".join(note_parts),
                )
            )
            self.rotation.record_drive(driver, duration)
            last_driver_name = driver.name
            current_min += duration
            stint_number += 1
            stint_index += 1

            if is_final:
                break

            pit_min = current_min
            window_idx = self.pit_windows.window_index_for_pit(pit_min)
            if window_idx is not None:
                satisfied_windows.add(window_idx)

            current_min += self.config.pit_loss_sec / 60.0
            pit_stops += 1

        plan = StintPlan(
            config=self.config,
            stints=stints,
            total_pit_stops=pit_stops,
            regulations=self.regulations,
        )
        if self.regulations:
            validator = RegulationValidator(
                self.regulations, self.config.race_duration_min
            )
            warnings, errors = validator.validate(stints, self.drivers)
            plan.warnings = warnings
            plan.errors = errors
        else:
            plan.warnings = validate_driver_totals(
                self.drivers,
                drive_totals_from_stints(stints),
            )
        return plan


class SafetyCarReplanner:
    def __init__(
        self,
        config: RaceConfig,
        drivers: list[Driver],
        regulations: Optional[SeriesRegulations] = None,
        compounds: Optional[list[TyreCompound]] = None,
        sc_pit_loss_sec: float = 25.0,
        sc_fuel_saving_laps: int = 1,
    ):
        self.config = config
        self.drivers = drivers
        self.regulations = regulations
        self.compounds = compounds
        self.sc_pit_loss_sec = sc_pit_loss_sec
        self.sc_fuel_saving_laps = sc_fuel_saving_laps
        self.fuel_calc = FuelCalculator(config)

    def replan(
        self,
        original_plan: StintPlan,
        sc_deployed_min: float,
        extend_current_stint_min: float = 0.0,
    ) -> StintPlan:
        completed_stints: list[Stint] = []
        active_stint: Optional[Stint] = None

        for stint in original_plan.stints:
            if stint.end_min <= sc_deployed_min:
                completed_stints.append(stint)
            elif stint.start_min <= sc_deployed_min < stint.end_min:
                active_stint = stint
                break
            else:
                break

        if active_stint is None:
            resume_min = sc_deployed_min
            if completed_stints:
                last_driver = completed_stints[-1].driver
                names = [d.name for d in self.drivers]
                idx = names.index(last_driver.name)
                resume_driver = self.drivers[(idx + 1) % len(self.drivers)]
            else:
                resume_driver = self.drivers[0]
        else:
            elapsed = sc_deployed_min - active_stint.start_min
            extended = min(
                elapsed + extend_current_stint_min,
                active_stint.driver.effective_max_stint(self.regulations),
            )
            extended = max(extended, elapsed)
            laps = self.fuel_calc.laps_for_minutes(extended)
            completed_stints.append(
                Stint(
                    stint_number=active_stint.stint_number,
                    driver=active_stint.driver,
                    start_min=active_stint.start_min,
                    duration_min=extended,
                    laps=laps,
                    fuel_used_liters=self.fuel_calc.fuel_for_laps(laps),
                    tyre_compound=active_stint.tyre_compound,
                    notes=f"Extended under SC (+{format_duration(extend_current_stint_min)})",
                )
            )
            resume_min = completed_stints[-1].end_min + self.sc_pit_loss_sec / 60.0
            names = [d.name for d in self.drivers]
            idx = names.index(active_stint.driver.name)
            resume_driver = self.drivers[(idx + 1) % len(self.drivers)]

        race_end = self.config.race_duration_min
        if resume_min >= race_end:
            return StintPlan(
                config=self.config,
                stints=completed_stints,
                total_pit_stops=max(0, len(completed_stints) - 1),
                warnings=["SC deployment leaves no remaining race time."],
                regulations=self.regulations,
            )

        sc_config = RaceConfig(
            race_name=(
                f"{self.config.race_name} "
                f"(SC Re-plan @ {format_duration(sc_deployed_min)})"
            ),
            race_duration_min=self.config.race_duration_min,
            lap_time_sec=self.config.lap_time_sec,
            fuel_tank_liters=self.config.fuel_tank_liters,
            fuel_per_lap_liters=self.config.fuel_per_lap_liters,
            fuel_safety_laps=max(0, self.config.fuel_safety_laps - self.sc_fuel_saving_laps),
            pit_loss_sec=self.sc_pit_loss_sec,
            formation_lap_min=0.0,
            series_id=self.config.series_id,
        )

        planner = StintPlanner(
            sc_config, self.drivers, self.regulations, self.compounds
        )
        planner.rotation.set_current_driver(resume_driver)
        for stint in completed_stints:
            planner.rotation.record_drive(stint.driver, stint.duration_min)

        prior_windows = satisfied_windows_from_stints(
            completed_stints,
            self.regulations,
            self.config.race_duration_min,
        )
        remainder = planner.build_plan(
            start_min=resume_min,
            race_end_min=race_end,
            stint_start_number=len(completed_stints) + 1,
            skip_formation=True,
            preserve_rotation=True,
            initial_satisfied_windows=prior_windows,
        )

        merged = list(completed_stints)
        for stint in remainder.stints:
            stint.notes = ("SC re-plan | " + stint.notes).strip(" |")
            merged.append(stint)

        warnings = [f"Safety Car re-plan from {format_duration(sc_deployed_min)}"]
        errors: list[str] = []
        if self.regulations:
            validator = RegulationValidator(
                self.regulations, self.config.race_duration_min
            )
            reg_warnings, reg_errors = validator.validate(merged, self.drivers)
            warnings.extend(reg_warnings)
            errors.extend(reg_errors)
        else:
            warnings.extend(
                validate_driver_totals(
                    self.drivers, drive_totals_from_stints(merged)
                )
            )

        return StintPlan(
            config=sc_config,
            stints=merged,
            total_pit_stops=max(0, len(merged) - 1),
            warnings=warnings,
            errors=errors,
            regulations=self.regulations,
        )


# ---------------------------------------------------------------------------
# Gap / crossover simulation
# ---------------------------------------------------------------------------

@dataclass
class GapSimulationConfig:
    """Inputs for basic track-position crossover modelling."""
    gap_to_leader_sec: float
    leader_lap_time_sec: float
    our_base_lap_time_sec: float
    our_pit_loss_sec: float
    leader_pit_loss_sec: float
    cars_ahead: int = 0
    cars_behind: int = 0


@dataclass
class PitOptionResult:
    label: str
    pit_at_lap: int
    gap_after_sec: float
    gap_change_sec: float
    track_position_note: str


class GapSimulator:
    """
    Simple static-gap crossover model.

    Compares estimated gap to leader after pitting at different laps.
    Assumes constant lap times and fixed pit loss — no traffic or SC.
    """

    def __init__(self, config: GapSimulationConfig):
        self.config = config

    def evaluate_pit_options(
        self,
        stint_laps: int,
        pit_lap_options: Optional[list[int]] = None,
    ) -> list[PitOptionResult]:
        cfg = self.config
        options = pit_lap_options or [
            max(1, stint_laps - 2),
            max(1, stint_laps - 1),
            stint_laps,
        ]
        results = []
        for pit_lap in sorted(set(options)):
            if pit_lap < 1 or pit_lap > stint_laps:
                continue
            # Time while leader pits (if they pit on same lap — simplified).
            our_running = pit_lap * cfg.our_base_lap_time_sec
            leader_running = pit_lap * cfg.leader_lap_time_sec
            our_total = our_running + cfg.our_pit_loss_sec
            leader_total = leader_running  # stay out scenario
            gap_after = cfg.gap_to_leader_sec + (our_total - leader_total)

            change = gap_after - cfg.gap_to_leader_sec
            if change < -5:
                note = "Likely gain vs leader (undercut)"
            elif change > 5:
                note = "Likely loss vs leader (late stop)"
            else:
                note = "Neutral crossover band"

            results.append(
                PitOptionResult(
                    label=f"Pit lap {pit_lap}",
                    pit_at_lap=pit_lap,
                    gap_after_sec=gap_after,
                    gap_change_sec=change,
                    track_position_note=note,
                )
            )
        return results


def print_gap_analysis(
    results: list[PitOptionResult],
    config: GapSimulationConfig,
) -> None:
    print("\n" + "=" * 80)
    print("  GAP / CROSSOVER ANALYSIS")
    print("=" * 80)
    print(
        f"  Gap to leader: {config.gap_to_leader_sec:.1f}s  |  "
        f"Our pace: {config.our_base_lap_time_sec:.3f}s  |  "
        f"Leader pace: {config.leader_lap_time_sec:.3f}s"
    )
    print(
        f"  Our pit loss: {config.our_pit_loss_sec:.0f}s  |  "
        f"Leader pit loss: {config.leader_pit_loss_sec:.0f}s"
    )
    print("-" * 80)
    for r in results:
        sign = "+" if r.gap_change_sec >= 0 else ""
        print(
            f"  {r.label:14s}  Gap after: {r.gap_after_sec:7.1f}s  "
            f"({sign}{r.gap_change_sec:.1f}s)  — {r.track_position_note}"
        )
    print("=" * 80 + "\n")


# ---------------------------------------------------------------------------
# Real-race validation case study
# ---------------------------------------------------------------------------

@dataclass
class ActualStintRecord:
    stint_number: int
    duration_min: float
    notes: str = ""


@dataclass
class ValidationCaseStudy:
    """
    Compare model output against published stint times.

    Fun Cup Portimão 2024 8h — Car #424 (Bollen-Leenders), classified P2.
    Stint durations from official Fun Racing Cars pit/stint timing PDF.
    Source: resultscdn.getraceresults.com (Oct 2024, Algarve 8h).
    """
    name: str
    source: str
    assumptions: list[str]
    actual_stints: list[ActualStintRecord]

    def compare(self, plan: StintPlan) -> pd.DataFrame:
        rows = []
        max_len = max(len(self.actual_stints), len(plan.stints))
        for i in range(max_len):
            actual = self.actual_stints[i] if i < len(self.actual_stints) else None
            model = plan.stints[i] if i < len(plan.stints) else None
            actual_min = actual.duration_min if actual else None
            model_min = model.duration_min if model else None
            delta = None
            if actual_min is not None and model_min is not None:
                delta = model_min - actual_min
            rows.append({
                "Stint": i + 1,
                "Actual": format_duration(actual_min) if actual_min else "-",
                "Model": format_duration(model_min) if model_min else "-",
                "Delta (min)": round(delta, 1) if delta is not None else "-",
                "Model Tyre": model.tyre_compound.value if model else "-",
                "Model Limit": model.limiting_factor if model else "-",
                "Actual Notes": actual.notes if actual else "-",
            })
        return pd.DataFrame(rows)


FUN_CUP_PORTIMAO_2024_CASE = ValidationCaseStudy(
    name="Fun Cup Portimão 2024 — #424 Bollen-Leenders (P2, 8h)",
    source=(
        "Fun Racing Cars 2024 Portimão 8h — Pit and Stint-times PDF "
        "(getraceresults.com / livetiming.raceresults.nu)"
    ),
    assumptions=[
        "8h race duration; lap time 2:08 (128s) from long-run estimate at Algarve.",
        "Fuel 2.55 L/lap, 80 L tank — calibrated to ~30 lap fuel stints.",
        "Giti GTR2: max 22 laps/stint, 0.08s/lap deg (calibrated to ~38 min stints).",
        "Driver-balance rule (§2.4.3): neither driver > 2× the other.",
        "8h mandatory windows excluded — set per-event, not in 2024 handbook.",
        "Pit loss 105s modelled (actual team ~105s total per stop incl. in+out+work).",
        "Model does not simulate traffic, SC periods, or repairs.",
    ],
    actual_stints=[
        ActualStintRecord(1, 49.8, "Opening stint incl. traffic"),
        ActualStintRecord(2, 37.85),
        ActualStintRecord(3, 38.6),
        ActualStintRecord(4, 36.48),
        ActualStintRecord(5, 40.8),
        ActualStintRecord(6, 22.42, "Short stop before long run"),
        ActualStintRecord(7, 54.1, "Double-stint attempt"),
        ActualStintRecord(8, 36.88),
        ActualStintRecord(9, 38.62),
        ActualStintRecord(10, 38.4),
        ActualStintRecord(11, 7.82, "Partial stint to window"),
        ActualStintRecord(12, 16.72),
    ],
)


def run_validation_case(
    case: ValidationCaseStudy = FUN_CUP_PORTIMAO_2024_CASE,
) -> tuple[StintPlan, pd.DataFrame]:
    """Build model plan for case-study parameters and compare to reality."""
    config = RaceConfig(
        race_name=case.name,
        race_duration_min=480.0,
        lap_time_sec=128.0,
        fuel_tank_liters=80.0,
        fuel_per_lap_liters=2.55,
        fuel_safety_laps=1,
        pit_loss_sec=105.0,
        formation_lap_min=5.0,
        series_id="fun-cup-validation",
    )
    drivers = [
        Driver(name="Bollen", category=DriverCategory.PRO, max_stint_min=55.0),
        Driver(name="Leenders", category=DriverCategory.PRO, max_stint_min=55.0),
    ]
    regs = fun_cup_validation_regulations()
    # Calibrated GTR2 profile for ~38 min stints at Portimão pace.
    gtr2_calibrated = TyreProfile(
        compound=TyreCompound.GTR2,
        max_laps=18,
        deg_per_lap_sec=0.08,
        cliff_lap=15,
    )
    original_gtr2 = TYRE_PROFILES[TyreCompound.GTR2]
    TYRE_PROFILES[TyreCompound.GTR2] = gtr2_calibrated
    try:
        planner = StintPlanner(
            config, drivers, regs, [TyreCompound.GTR2]
        )
        plan = planner.build_plan()
    finally:
        TYRE_PROFILES[TyreCompound.GTR2] = original_gtr2
    comparison = case.compare(plan)
    return plan, comparison


def print_validation_report(
    case: ValidationCaseStudy,
    plan: StintPlan,
    comparison: pd.DataFrame,
) -> None:
    print("\n" + "=" * 100)
    print(f"  VALIDATION CASE STUDY — {case.name}")
    print("=" * 100)
    print(f"  Source: {case.source}")
    print("\n  Assumptions:")
    for item in case.assumptions:
        print(f"    • {item}")
    print("\n  Comparison (model vs actual stint durations):")
    print(comparison.to_string(index=False))
    print("\n  Model summary:")
    print(f"    Stints: {len(plan.stints)} (actual: {len(case.actual_stints)})")
    print(f"    Pit stops: {plan.total_pit_stops}")
    if plan.errors:
        print("\n  Regulation errors:")
        for e in plan.errors:
            print(f"    ✗ {e}")
    if plan.warnings:
        print("\n  Warnings:")
        for w in plan.warnings:
            print(f"    ! {w}")
    deltas = comparison["Delta (min)"].replace("-", float("nan"))
    numeric = pd.to_numeric(deltas, errors="coerce").dropna()
    if len(numeric):
        print(
            f"\n  Mean absolute stint delta: "
            f"{numeric.abs().mean():.1f} min  |  "
            f"Max delta: {numeric.abs().max():.1f} min"
        )
        print(
            "  Interpretation: deltas reflect SC/traffic/repairs not modelled, "
            "plus tyre-age and driver-pace variability."
        )
    print("=" * 100 + "\n")


# ---------------------------------------------------------------------------
# Output and visualization
# ---------------------------------------------------------------------------

def print_plan_table(plan: StintPlan) -> None:
    df = plan.to_dataframe()
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    print("\n" + "=" * 110)
    print(f"  STINT PLAN — {plan.config.race_name}")
    if plan.regulations:
        print(f"  Regulations: {plan.regulations.name}")
    print("=" * 110)
    print(df.to_string(index=False))
    print("=" * 110)

    summary = plan.summary()
    print(
        f"\nTotal stints: {summary['total_stints']}  |  "
        f"Pit stops: {summary['total_pit_stops']}"
    )
    print("\nDriver totals:")
    race_minutes = plan.race_end_min
    for name, minutes in summary["driver_minutes"].items():
        pct = 100.0 * minutes / race_minutes if race_minutes else 0.0
        print(f"  {name:20s}  {format_duration(minutes)}  ({pct:.1f}% of race)")

    if plan.errors:
        print("\nRegulation ERRORS:")
        for err in plan.errors:
            print(f"  ✗ {err}")
    if plan.warnings:
        print("\nStrategy warnings:")
        for warning in plan.warnings:
            print(f"  ! {warning}")
    print()


def plot_stint_timeline(
    plan: StintPlan,
    output_path: Optional[Path] = None,
    show: bool = True,
) -> None:
    if not plan.stints:
        print("No stints to plot.")
        return

    category_colors = {
        DriverCategory.PRO: "#E63946",
        DriverCategory.SILVER: "#457B9D",
        DriverCategory.BRONZE: "#F4A261",
        DriverCategory.AMATEUR: "#2A9D8F",
    }

    fig, ax = plt.subplots(figsize=(14, max(3, len(plan.stints) * 0.55 + 1.5)))
    race_end = plan.race_end_min

    for index, stint in enumerate(plan.stints):
        color = category_colors.get(stint.driver.category, "#6C757D")
        ax.barh(
            y=index, width=stint.duration_min, left=stint.start_min,
            height=0.6, color=color, edgecolor="white", linewidth=0.8,
        )
        ax.text(
            stint.start_min + stint.duration_min / 2, index,
            f"{stint.driver.name}\n{stint.laps}L {stint.tyre_compound.value}",
            ha="center", va="center", fontsize=7, color="white", fontweight="bold",
        )
        if stint.pit_window_open_min is not None and stint.pit_window_close_min:
            ax.plot(
                [stint.pit_window_open_min, stint.pit_window_close_min],
                [index + 0.38, index + 0.38],
                color="white", linestyle="--", linewidth=1.5, alpha=0.9,
            )

    if plan.regulations:
        for window in plan.regulations.windows_for_duration(race_end):
            ax.axvspan(
                window.open_min, window.close_min,
                alpha=0.08, color="yellow", zorder=0,
            )

    ax.set_xlim(0, race_end * 1.02)
    ax.set_ylim(-0.5, len(plan.stints) - 0.5)
    ax.set_xlabel("Race Time (minutes)")
    ax.set_ylabel("Stint")
    ax.set_title(f"Stint Timeline — {plan.config.race_name}", fontsize=13, fontweight="bold")
    ax.set_yticks(range(len(plan.stints)))
    ax.set_yticklabels([f"S{s.stint_number}" for s in plan.stints])
    ax.axvline(x=race_end, color="black", linestyle=":", linewidth=1)
    ax.grid(axis="x", alpha=0.3)

    seen: set[DriverCategory] = set()
    patches = []
    for stint in plan.stints:
        if stint.driver.category not in seen:
            patches.append(mpatches.Patch(
                color=category_colors[stint.driver.category],
                label=stint.driver.category.value,
            ))
            seen.add(stint.driver.category)
    ax.legend(handles=patches, loc="upper right", framealpha=0.9)
    plt.tight_layout()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"Timeline saved to {output_path}")
    if show:
        plt.show()
    else:
        plt.close(fig)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def fun_cup_preset() -> PresetBundle:
    config = RaceConfig(
        race_name="Fun Cup — 4h Portimao",
        race_duration_min=240.0,
        lap_time_sec=128.0,
        fuel_tank_liters=80.0,
        fuel_per_lap_liters=2.6,
        fuel_safety_laps=1,
        pit_loss_sec=50.0,
        formation_lap_min=5.0,
        series_id="fun-cup-gt4",
    )
    drivers = [
        Driver(name="Martin Pro", category=DriverCategory.PRO, max_stint_min=90.0),
        Driver(name="Lucas Bronze", category=DriverCategory.AMATEUR, max_stint_min=90.0),
    ]
    return PresetBundle(
        config, drivers, fun_cup_gt4_regulations(),
        [TyreCompound.GTR2],
    )


def elms_lmgt3_preset() -> PresetBundle:
    config = RaceConfig(
        race_name="ELMS — 6h Spa-Francorchamps (LMGT3)",
        race_duration_min=360.0,
        lap_time_sec=142.0,
        fuel_tank_liters=110.0,
        fuel_per_lap_liters=3.1,
        fuel_safety_laps=1,
        pit_loss_sec=48.0,
        formation_lap_min=6.0,
        series_id="elms-lmgt3",
    )
    drivers = [
        Driver(name="Antoine Pro", category=DriverCategory.PRO, max_stint_min=120.0),
        Driver(name="Sophie Bronze", category=DriverCategory.BRONZE, max_stint_min=65.0),
        Driver(name="James Silver", category=DriverCategory.SILVER, max_stint_min=90.0),
    ]
    return PresetBundle(
        config, drivers, elms_lmgt3_regulations(),
        [TyreCompound.MEDIUM, TyreCompound.HARD, TyreCompound.MEDIUM],
    )


def wec_hypercar_preset() -> PresetBundle:
    config = RaceConfig(
        race_name="WEC — 6h Fuji (Hypercar)",
        race_duration_min=360.0,
        lap_time_sec=105.0,
        fuel_tank_liters=90.0,
        fuel_per_lap_liters=2.9,
        fuel_safety_laps=1,
        pit_loss_sec=42.0,
        formation_lap_min=5.0,
        series_id="wec-hypercar",
    )
    drivers = [
        Driver(name="Kamui Pro", category=DriverCategory.PRO, max_stint_min=120.0),
        Driver(name="Pietro Bronze", category=DriverCategory.BRONZE, max_stint_min=65.0),
        Driver(name="Jenson Pro", category=DriverCategory.PRO, max_stint_min=120.0),
    ]
    return PresetBundle(
        config, drivers, wec_hypercar_regulations(),
        [TyreCompound.MEDIUM, TyreCompound.HARD],
    )


PRESETS: dict[str, callable] = {
    "fun-cup": fun_cup_preset,
    "elms": elms_lmgt3_preset,
    "wec": wec_hypercar_preset,
}


def parse_compounds(spec: str) -> list[TyreCompound]:
    compounds = []
    for part in spec.split(","):
        part = part.strip().upper()
        try:
            compounds.append(TyreCompound(part))
        except ValueError as exc:
            valid = ", ".join(c.value for c in TyreCompound)
            raise ValueError(
                f"Unknown compound '{part}'. Use: {valid}"
            ) from exc
    return compounds


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Endurance Race Stint Planner — fuel/tyre stints, regulations, "
            "gap simulation, Safety Car re-plan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python endurance_stint_planner.py --preset fun-cup
  python endurance_stint_planner.py --preset elms --compounds MEDIUM,HARD,MEDIUM
  python endurance_stint_planner.py --preset fun-cup --gap-sim --gap-to-leader 12
  python endurance_stint_planner.py --validate-case
  python endurance_stint_planner.py --preset fun-cup --safety-car 125 --extend-stint 8
        """,
    )
    parser.add_argument("--preset", choices=list(PRESETS.keys()))
    parser.add_argument("--race-hours", type=float)
    parser.add_argument("--race-name", type=str, default="Custom Endurance Race")
    parser.add_argument("--lap-time", type=str)
    parser.add_argument("--tank", type=float)
    parser.add_argument("--fuel-per-lap", type=float)
    parser.add_argument("--safety-laps", type=int, default=1)
    parser.add_argument("--pit-loss", type=float, default=45.0)
    parser.add_argument("--drivers", type=str)
    parser.add_argument(
        "--compounds",
        type=str,
        help="Comma-separated tyre compounds per stint (GTR2, MEDIUM, HARD, SOFT).",
    )
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--export-csv", type=Path)
    parser.add_argument("--safety-car", type=float, metavar="MINUTE")
    parser.add_argument("--extend-stint", type=float, default=0.0)
    parser.add_argument("--sc-pit-loss", type=float, default=25.0)
    parser.add_argument(
        "--gap-sim",
        action="store_true",
        help="Run gap/crossover analysis for first stint pit options.",
    )
    parser.add_argument("--gap-to-leader", type=float, default=15.0,
                        help="Gap to leader in seconds (default 15).")
    parser.add_argument("--leader-lap-time", type=str,
                        help="Leader lap time (default: same as ours).")
    parser.add_argument("--leader-pit-loss", type=float, default=50.0)
    parser.add_argument(
        "--validate-case",
        action="store_true",
        help="Run Fun Cup Portimão 2024 validation case study.",
    )
    return parser


def parse_driver_spec(spec: str) -> Driver:
    parts = [p.strip() for p in spec.strip().split(":")]
    if len(parts) < 2:
        raise ValueError(f"Invalid driver spec: {spec}")
    name = parts[0]
    if not name:
        raise ValueError(f"Driver name required: {spec}")
    try:
        category = DriverCategory(parts[1])
    except ValueError as exc:
        valid = ", ".join(c.value for c in DriverCategory)
        raise ValueError(f"Invalid category in {spec}. Use: {valid}") from exc
    min_stint = parse_optional_float(parts[2], 45.0) if len(parts) > 2 else 45.0
    max_stint = parse_optional_float(parts[3], 90.0) if len(parts) > 3 else 90.0
    min_total = parse_optional_float(parts[4], 0.0) if len(parts) > 4 else 0.0
    return Driver(name, category, min_stint, max_stint, min_total)


def config_from_args(
    args: argparse.Namespace,
) -> tuple[RaceConfig, list[Driver], Optional[SeriesRegulations], list[TyreCompound]]:
    compounds: list[TyreCompound] = []
    if args.compounds:
        compounds = parse_compounds(args.compounds)

    if args.preset:
        bundle = PRESETS[args.preset]()
        if compounds:
            return bundle.config, bundle.drivers, bundle.regulations, compounds
        return bundle.config, bundle.drivers, bundle.regulations, bundle.default_compounds

    if not all([args.race_hours, args.lap_time, args.tank, args.fuel_per_lap]):
        raise ValueError(
            "Custom mode requires --race-hours, --lap-time, --tank, "
            "--fuel-per-lap (or use --preset)."
        )
    config = RaceConfig(
        race_name=args.race_name,
        race_duration_min=args.race_hours * 60.0,
        lap_time_sec=parse_lap_time(args.lap_time),
        fuel_tank_liters=args.tank,
        fuel_per_lap_liters=args.fuel_per_lap,
        fuel_safety_laps=args.safety_laps,
        pit_loss_sec=args.pit_loss,
    )
    if args.drivers:
        drivers = [parse_driver_spec(s) for s in args.drivers.split(",")]
    else:
        drivers = [
            Driver("Driver A", DriverCategory.PRO),
            Driver("Driver B", DriverCategory.BRONZE,
                   min_total_drive_min=args.race_hours * 60 * 0.4),
        ]
    default_compounds = compounds or [TyreCompound.MEDIUM]
    return config, drivers, None, default_compounds


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.validate_case:
        plan, comparison = run_validation_case()
        print_validation_report(FUN_CUP_PORTIMAO_2024_CASE, plan, comparison)
        return 0

    if not args.preset and not args.race_hours:
        parser.print_help()
        print("\nTip: python endurance_stint_planner.py --preset fun-cup\n", file=sys.stderr)
        return 1

    try:
        config, drivers, regulations, compounds = config_from_args(args)
    except (ValueError, KeyError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    planner = StintPlanner(config, drivers, regulations, compounds)
    plan = planner.build_plan()

    fuel_calc = FuelCalculator(config)
    tyre_calc = TyreCalculator(
        TYRE_PROFILES[compounds[0]], config.lap_time_sec
    )
    print(
        f"\nFuel geometry: {fuel_calc.max_stint_laps()} laps/stint "
        f"({format_duration(fuel_calc.max_stint_minutes())})"
    )
    print(
        f"Tyre geometry ({compounds[0].value}): "
        f"{tyre_calc.max_stint_laps()} laps/stint "
        f"({format_duration(tyre_calc.max_stint_minutes())}) — "
        f"{tyre_calc.limiting_factor(fuel_calc.max_stint_laps())}"
    )
    print(
        f"Lap time: {config.lap_time_sec:.3f}s  |  "
        f"Consumption: {config.fuel_per_lap_liters:.2f} L/lap  |  "
        f"Tank: {config.fuel_tank_liters:.0f} L"
    )
    if regulations:
        print(f"Regulations: {regulations.name}")
        print(f"  Ref: {regulations.regulation_ref}")

    if args.safety_car is not None:
        replanner = SafetyCarReplanner(
            config, drivers, regulations, compounds,
            sc_pit_loss_sec=args.sc_pit_loss,
        )
        plan = replanner.replan(plan, args.safety_car, args.extend_stint)
        print(f"\n[SC] Re-plan from {format_duration(args.safety_car)}")

    print_plan_table(plan)

    if args.gap_sim and plan.stints:
        first = plan.stints[0]
        leader_lt = (
            parse_lap_time(args.leader_lap_time)
            if args.leader_lap_time
            else config.lap_time_sec
        )
        gap_cfg = GapSimulationConfig(
            gap_to_leader_sec=args.gap_to_leader,
            leader_lap_time_sec=leader_lt,
            our_base_lap_time_sec=config.lap_time_sec,
            our_pit_loss_sec=config.pit_loss_sec,
            leader_pit_loss_sec=args.leader_pit_loss,
        )
        sim = GapSimulator(gap_cfg)
        results = sim.evaluate_pit_options(first.laps)
        print_gap_analysis(results, gap_cfg)

    if args.export_csv:
        args.export_csv.parent.mkdir(parents=True, exist_ok=True)
        plan.to_dataframe().to_csv(args.export_csv, index=False)
        print(f"CSV exported to {args.export_csv}")

    if args.plot or args.output:
        if args.output and not args.plot:
            plt.switch_backend("Agg")
        plot_stint_timeline(plan, output_path=args.output, show=args.plot)

    return 0


def run_self_tests() -> None:
    tests = [
        ["--preset", "fun-cup"],
        ["--preset", "elms"],
        ["--preset", "wec", "--safety-car", "185", "--extend-stint", "8"],
        ["--preset", "fun-cup", "--gap-sim", "--gap-to-leader", "10"],
        ["--validate-case"],
        [
            "--race-hours", "4", "--lap-time", "2:08",
            "--tank", "80", "--fuel-per-lap", "2.6",
            "--compounds", "GTR2,GTR2",
            "--drivers", "A:Pro::90:0,B:Amateur:45:90:0",
        ],
    ]
    for argv in tests:
        if main(argv) != 0:
            raise RuntimeError(f"Self-test failed: {argv}")
    print("All self-tests passed.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        run_self_tests()
    else:
        raise SystemExit(main())