#!/usr/bin/env python3
"""
Endurance Race Stint Planner
============================

Strategy planning tool for endurance sportscar racing (Lamera Cup, Fun Cup,
ELMS, WEC). Computes fuel-limited stint lengths, driver rotations with
regulatory min/max drive times, pit window targets, and Safety Car re-plans.

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
    """
    Parse lap time string to seconds.
    Accepts '125' (seconds), '2:05', or '1:42.500'.
    """
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
    """Parse a CLI field that may be left blank to use a default."""
    value = value.strip()
    return float(value) if value else default


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class DriverCategory(Enum):
    """FIA driver grading used in WEC / ELMS / Bronze-focused series."""
    PRO = "Pro"
    SILVER = "Silver"
    BRONZE = "Bronze"
    AMATEUR = "Amateur"


@dataclass
class Driver:
    """Driver profile with regulatory stint constraints."""
    name: str
    category: DriverCategory
    min_stint_min: float = 45.0
    max_stint_min: float = 90.0
    min_total_drive_min: float = 0.0

    def effective_max_stint(self) -> float:
        """Bronze drivers face a stricter per-stint cap in most championships."""
        if self.category == DriverCategory.BRONZE:
            return min(self.max_stint_min, 65.0)
        return self.max_stint_min


@dataclass
class RaceConfig:
    """Static race and car parameters for stint simulation."""
    race_name: str
    race_duration_min: float
    lap_time_sec: float
    fuel_tank_liters: float
    fuel_per_lap_liters: float
    fuel_safety_laps: int = 1
    pit_loss_sec: float = 45.0
    formation_lap_min: float = 5.0

    @property
    def lap_time_min(self) -> float:
        return self.lap_time_sec / 60.0

    def laps_per_stint(self) -> int:
        """
        Fuel-limited stint length in laps.

        Strategy: keep a safety margin in the tank to cover consumption drift,
        traffic, and Safety Car periods at higher burn.
        """
        usable_fuel = self.fuel_tank_liters - (
            self.fuel_safety_laps * self.fuel_per_lap_liters
        )
        if usable_fuel <= 0:
            raise ValueError("Fuel tank too small for configured safety margin.")
        return int(math.floor(usable_fuel / self.fuel_per_lap_liters))

    def stint_duration_min(self, laps: Optional[int] = None) -> float:
        """Convert lap count to stint duration in minutes."""
        lap_count = laps if laps is not None else self.laps_per_stint()
        return lap_count * self.lap_time_min


@dataclass
class Stint:
    """A single driving stint between pit stops."""
    stint_number: int
    driver: Driver
    start_min: float
    duration_min: float
    laps: int
    fuel_used_liters: float
    pit_window_open_min: Optional[float] = None
    pit_window_close_min: Optional[float] = None
    notes: str = ""

    @property
    def end_min(self) -> float:
        return self.start_min + self.duration_min

    def to_dict(self) -> dict:
        return {
            "Stint": self.stint_number,
            "Driver": self.driver.name,
            "Category": self.driver.category.value,
            "Start": format_duration(self.start_min),
            "End": format_duration(self.end_min),
            "Duration": format_duration(self.duration_min),
            "Laps": self.laps,
            "Fuel (L)": round(self.fuel_used_liters, 1),
            "Pit Window Open": (
                format_duration(self.pit_window_open_min)
                if self.pit_window_open_min is not None
                else "-"
            ),
            "Pit Window Close": (
                format_duration(self.pit_window_close_min)
                if self.pit_window_close_min is not None
                else "-"
            ),
            "Notes": self.notes,
        }


@dataclass
class StintPlan:
    """Complete race stint schedule."""
    config: RaceConfig
    stints: list[Stint] = field(default_factory=list)
    total_pit_stops: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def race_end_min(self) -> float:
        """Chequered-flag time used for summaries and charts."""
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
        }


# ---------------------------------------------------------------------------
# Core planning logic
# ---------------------------------------------------------------------------

class FuelCalculator:
    """Fuel-limited stint geometry — the backbone of endurance strategy."""

    def __init__(self, config: RaceConfig):
        self.config = config

    def max_stint_laps(self) -> int:
        return self.config.laps_per_stint()

    def max_stint_minutes(self) -> float:
        return self.config.stint_duration_min()

    def fuel_for_laps(self, laps: int) -> float:
        return laps * self.config.fuel_per_lap_liters

    def laps_for_minutes(self, minutes: float) -> int:
        """Floor lap count achievable within a time budget."""
        if minutes <= 0:
            return 0
        return int(math.floor(minutes / self.config.lap_time_min))

    def minutes_for_laps(self, laps: int) -> float:
        return laps * self.config.lap_time_min


class DriverRotationManager:
    """
    Manages driver hand-offs respecting per-stint and total-drive regulations.

    Typical Pro + Bronze lineup (Fun Cup / Lamera Cup / ELMS LMGT3):
      - Bronze: min 45 min/stint, max 65 min/stint, min total drive ~40% of race
      - Pro: longer stints to cover remaining seat time efficiently
    """

    def __init__(self, drivers: list[Driver]):
        if not drivers:
            raise ValueError("At least one driver is required.")
        self.drivers = drivers
        self._index = 0
        self._cumulative_drive: dict[str, float] = {d.name: 0.0 for d in drivers}

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
        remaining_race_min: float,
    ) -> float:
        """
        Effective stint cap = min(fuel range, driver max, remaining race time).
        """
        cap = min(
            fuel_limited_min,
            driver.effective_max_stint(),
            remaining_race_min,
        )
        return max(cap, 0.0)

    def select_priority_driver(
        self,
        fuel_limited_min: float,
        remaining_race_min: float,
        avoid_driver_name: Optional[str] = None,
    ) -> None:
        """
        Pick the next driver, favouring anyone below their minimum total drive.

        Strategy: meet Bronze quotas without stacking consecutive stints for
        the same driver when another lineup choice is available.
        """
        next_index = (self._index + 1) % len(self.drivers)
        best_index = next_index
        best_deficit = 0.0

        for index, driver in enumerate(self.drivers):
            if avoid_driver_name and driver.name == avoid_driver_name:
                continue

            driven = self._cumulative_drive[driver.name]
            deficit = max(0.0, driver.min_total_drive_min - driven)
            stint_cap = self.stint_cap_minutes(
                driver, fuel_limited_min, remaining_race_min
            )

            if stint_cap <= 0:
                continue

            if deficit > best_deficit:
                best_deficit = deficit
                best_index = index

        # Closing stints: satisfy any outstanding minimum-drive quota first.
        if remaining_race_min < fuel_limited_min * 1.5:
            for index, driver in enumerate(self.drivers):
                driven = self._cumulative_drive[driver.name]
                deficit = max(0.0, driver.min_total_drive_min - driven)
                stint_cap = self.stint_cap_minutes(
                    driver, fuel_limited_min, remaining_race_min
                )
                if deficit > 0 and stint_cap >= min(driver.min_stint_min, remaining_race_min):
                    self._index = index
                    return

        if best_deficit > 0:
            self._index = best_index
        else:
            self._index = next_index

    def validate_totals(self) -> list[str]:
        """Check minimum total drive requirements (e.g. Bronze 40% rule)."""
        return validate_driver_totals(self.drivers, self._cumulative_drive)


def validate_driver_totals(
    drivers: list[Driver],
    drive_minutes: dict[str, float],
) -> list[str]:
    """Check minimum total drive requirements across the full stint schedule."""
    warnings = []
    for driver in drivers:
        driven = drive_minutes.get(driver.name, 0.0)
        if driver.min_total_drive_min > 0 and driven < driver.min_total_drive_min:
            shortfall = driver.min_total_drive_min - driven
            warnings.append(
                f"{driver.name} ({driver.category.value}) short of minimum total "
                f"drive by {format_duration(shortfall)} "
                f"(driven {format_duration(driven)}, "
                f"required {format_duration(driver.min_total_drive_min)})."
            )
    return warnings


def drive_totals_from_stints(stints: list[Stint]) -> dict[str, float]:
    """Aggregate driving minutes per driver from a stint list."""
    totals: dict[str, float] = {}
    for stint in stints:
        totals[stint.driver.name] = (
            totals.get(stint.driver.name, 0.0) + stint.duration_min
        )
    return totals


class PitWindowPlanner:
    """
    Computes target pit windows for each stop.

    Strategy rationale:
      - Open window: earliest legal pit entry (after min stint)
      - Close window: latest pit entry before fuel runs critically low
    """

    def __init__(self, config: RaceConfig, fuel_calc: FuelCalculator):
        self.config = config
        self.fuel_calc = fuel_calc

    def compute_window(
        self,
        stint_start_min: float,
        stint_duration_min: float,
        driver: Driver,
    ) -> tuple[float, float]:
        window_open = stint_start_min + driver.min_stint_min
        window_close = stint_start_min + stint_duration_min
        return window_open, window_close


class StintPlanner:
    """Builds a full-race stint schedule from config and driver lineup."""

    def __init__(self, config: RaceConfig, drivers: list[Driver]):
        self.config = config
        self.drivers = drivers
        self.fuel_calc = FuelCalculator(config)
        self.rotation = DriverRotationManager(drivers)
        self.pit_windows = PitWindowPlanner(config, self.fuel_calc)

    def _compute_stint(
        self,
        driver: Driver,
        current_min: float,
        race_end: float,
        fuel_limited_min: float,
        max_laps: int,
    ) -> tuple[int, float, bool]:
        """Return laps, duration, and whether this is the final stint."""
        remaining = race_end - current_min
        duration = self.rotation.stint_cap_minutes(
            driver, fuel_limited_min, remaining
        )
        if duration <= 0:
            return 0, 0.0, True

        # Final stint when remaining time cannot fit another full fuel window.
        pit_loss_min = self.config.pit_loss_sec / 60.0
        is_final = remaining <= fuel_limited_min + pit_loss_min

        if is_final:
            laps = max(self.fuel_calc.laps_for_minutes(remaining), 1)
            duration = min(self.fuel_calc.minutes_for_laps(laps), remaining)
        else:
            laps = min(self.fuel_calc.laps_for_minutes(duration), max_laps)
            duration = self.fuel_calc.minutes_for_laps(laps)

            # Regulatory minimum stint on non-final stints.
            if duration < driver.min_stint_min:
                laps = min(
                    self.fuel_calc.laps_for_minutes(driver.min_stint_min),
                    max_laps,
                )
                duration = min(
                    self.fuel_calc.minutes_for_laps(laps),
                    remaining,
                )

        laps = max(laps, 0)
        return laps, duration, is_final

    def build_plan(
        self,
        start_min: float = 0.0,
        race_end_min: Optional[float] = None,
        stint_start_number: int = 1,
        skip_formation: bool = False,
        preserve_rotation: bool = False,
    ) -> StintPlan:
        """
        Generate stint sequence until race duration is covered.

        Loop logic:
          1. Select driver (priority to minimum-drive quotas)
          2. Cap stint by fuel, driver max, and remaining race time
          3. Attach pit window for strategist reference
          4. Rotate driver and repeat
        """
        if not preserve_rotation:
            self.rotation.reset()

        stints: list[Stint] = []
        stint_number = stint_start_number
        current_min = start_min + (
            0.0 if skip_formation else self.config.formation_lap_min
        )
        race_end = (
            race_end_min
            if race_end_min is not None
            else start_min + self.config.race_duration_min
        )
        fuel_limited_min = self.fuel_calc.max_stint_minutes()
        max_laps = self.fuel_calc.max_stint_laps()
        pit_stops = 0

        last_driver_name: Optional[str] = None

        while current_min < race_end - 0.5:
            remaining = race_end - current_min
            if stints:
                self.rotation.select_priority_driver(
                    fuel_limited_min,
                    remaining,
                    avoid_driver_name=last_driver_name,
                )
            driver = self.rotation.current_driver

            laps, duration, is_final = self._compute_stint(
                driver, current_min, race_end, fuel_limited_min, max_laps
            )
            if laps <= 0 or duration <= 0:
                break

            fuel_used = self.fuel_calc.fuel_for_laps(laps)
            window_open, window_close = self.pit_windows.compute_window(
                current_min, duration, driver
            )

            note = ""
            if is_final:
                note = "Final stint — check chequered flag overlap"
            elif duration >= fuel_limited_min * 0.98:
                note = "Fuel-limited stint"

            stints.append(
                Stint(
                    stint_number=stint_number,
                    driver=driver,
                    start_min=current_min,
                    duration_min=duration,
                    laps=laps,
                    fuel_used_liters=fuel_used,
                    pit_window_open_min=window_open if not is_final else None,
                    pit_window_close_min=window_close if not is_final else None,
                    notes=note,
                )
            )
            self.rotation.record_drive(driver, duration)
            last_driver_name = driver.name
            current_min += duration
            stint_number += 1

            if is_final:
                break

            current_min += self.config.pit_loss_sec / 60.0
            pit_stops += 1

        plan = StintPlan(
            config=self.config,
            stints=stints,
            total_pit_stops=pit_stops,
        )
        plan.warnings = self.rotation.validate_totals()
        return plan


class SafetyCarReplanner:
    """
    Re-plans remaining stints after a Safety Car or incident.

    SC strategy modelled here:
      - Extended stint under SC before pitting
      - Reduced pit loss (shorter in/out lap delta)
      - Fuel saved at SC pace → slightly relaxed safety margin
    """

    def __init__(
        self,
        config: RaceConfig,
        drivers: list[Driver],
        sc_pit_loss_sec: float = 25.0,
        sc_fuel_saving_laps: int = 1,
    ):
        self.config = config
        self.drivers = drivers
        self.sc_pit_loss_sec = sc_pit_loss_sec
        self.sc_fuel_saving_laps = sc_fuel_saving_laps
        self.fuel_calc = FuelCalculator(config)

    def replan(
        self,
        original_plan: StintPlan,
        sc_deployed_min: float,
        extend_current_stint_min: float = 0.0,
    ) -> StintPlan:
        """Rebuild plan from SC deployment point."""
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
            elapsed_in_stint = sc_deployed_min - active_stint.start_min
            extended_duration = elapsed_in_stint + extend_current_stint_min
            extended_duration = min(
                extended_duration,
                active_stint.driver.effective_max_stint(),
            )
            extended_duration = max(extended_duration, elapsed_in_stint)
            laps = self.fuel_calc.laps_for_minutes(extended_duration)

            sc_stint = Stint(
                stint_number=active_stint.stint_number,
                driver=active_stint.driver,
                start_min=active_stint.start_min,
                duration_min=extended_duration,
                laps=laps,
                fuel_used_liters=self.fuel_calc.fuel_for_laps(laps),
                notes=f"Extended under SC (+{format_duration(extend_current_stint_min)})",
            )
            completed_stints.append(sc_stint)
            resume_min = sc_stint.end_min + self.sc_pit_loss_sec / 60.0

            driver_names = [d.name for d in self.drivers]
            idx = driver_names.index(active_stint.driver.name)
            resume_driver = self.drivers[(idx + 1) % len(self.drivers)]

        original_race_end = self.config.race_duration_min
        if resume_min >= original_race_end:
            return StintPlan(
                config=self.config,
                stints=completed_stints,
                total_pit_stops=max(0, len(completed_stints) - 1),
                warnings=["SC deployment leaves no remaining race time."],
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
            fuel_safety_laps=max(
                0, self.config.fuel_safety_laps - self.sc_fuel_saving_laps
            ),
            pit_loss_sec=self.sc_pit_loss_sec,
            formation_lap_min=0.0,
        )

        planner = StintPlanner(sc_config, self.drivers)
        planner.rotation.set_current_driver(resume_driver)
        for stint in completed_stints:
            planner.rotation.record_drive(stint.driver, stint.duration_min)

        remainder_plan = planner.build_plan(
            start_min=resume_min,
            race_end_min=original_race_end,
            stint_start_number=len(completed_stints) + 1,
            skip_formation=True,
            preserve_rotation=True,
        )

        merged = list(completed_stints)
        for stint in remainder_plan.stints:
            stint.notes = ("SC re-plan | " + stint.notes).strip(" |")
            merged.append(stint)

        return StintPlan(
            config=sc_config,
            stints=merged,
            total_pit_stops=max(0, len(merged) - 1),
            warnings=(
                [f"Safety Car re-plan from {format_duration(sc_deployed_min)}"]
                + validate_driver_totals(
                    self.drivers, drive_totals_from_stints(merged)
                )
            ),
        )


# ---------------------------------------------------------------------------
# Output and visualization
# ---------------------------------------------------------------------------

def print_plan_table(plan: StintPlan) -> None:
    """Render stint plan as a formatted pandas table."""
    df = plan.to_dataframe()
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 100)
    print(f"  STINT PLAN — {plan.config.race_name}")
    print("=" * 100)
    print(df.to_string(index=False))
    print("=" * 100)

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

    if plan.warnings:
        print("\nStrategy warnings:")
        for warning in plan.warnings:
            print(f"  - {warning}")
    print()


def plot_stint_timeline(
    plan: StintPlan,
    output_path: Optional[Path] = None,
    show: bool = True,
) -> None:
    """Gantt-style stint timeline for pit-wall briefings."""
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
            y=index,
            width=stint.duration_min,
            left=stint.start_min,
            height=0.6,
            color=color,
            edgecolor="white",
            linewidth=0.8,
        )
        ax.text(
            stint.start_min + stint.duration_min / 2,
            index,
            f"{stint.driver.name}\n{stint.laps}L",
            ha="center",
            va="center",
            fontsize=8,
            color="white",
            fontweight="bold",
        )

        if (
            stint.pit_window_open_min is not None
            and stint.pit_window_close_min is not None
        ):
            ax.plot(
                [stint.pit_window_open_min, stint.pit_window_close_min],
                [index + 0.38, index + 0.38],
                color="white",
                linestyle="--",
                linewidth=1.5,
                alpha=0.9,
            )

    ax.set_xlim(0, race_end * 1.02)
    ax.set_ylim(-0.5, len(plan.stints) - 0.5)
    ax.set_xlabel("Race Time (minutes)")
    ax.set_ylabel("Stint")
    ax.set_title(
        f"Stint Timeline — {plan.config.race_name}",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_yticks(range(len(plan.stints)))
    ax.set_yticklabels([f"S{s.stint_number}" for s in plan.stints])
    ax.axvline(x=race_end, color="black", linestyle=":", linewidth=1)
    ax.grid(axis="x", alpha=0.3)

    seen: set[DriverCategory] = set()
    patches = []
    for stint in plan.stints:
        category = stint.driver.category
        if category not in seen:
            patches.append(
                mpatches.Patch(
                    color=category_colors[category],
                    label=category.value,
                )
            )
            seen.add(category)
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
# Preset configurations
# ---------------------------------------------------------------------------

def fun_cup_preset() -> tuple[RaceConfig, list[Driver]]:
    """Fun Cup / Lamera Cup — 4-hour GT4-style race (Pro + Bronze)."""
    config = RaceConfig(
        race_name="Fun Cup — 4h Portimao",
        race_duration_min=240.0,
        lap_time_sec=128.0,
        fuel_tank_liters=80.0,
        fuel_per_lap_liters=2.6,
        fuel_safety_laps=1,
        pit_loss_sec=50.0,
        formation_lap_min=5.0,
    )
    drivers = [
        Driver(
            name="Martin Pro",
            category=DriverCategory.PRO,
            min_stint_min=45.0,
            max_stint_min=90.0,
        ),
        Driver(
            name="Lucas Bronze",
            category=DriverCategory.BRONZE,
            min_stint_min=45.0,
            max_stint_min=65.0,
            min_total_drive_min=96.0,
        ),
    ]
    return config, drivers


def elms_lmgt3_preset() -> tuple[RaceConfig, list[Driver]]:
    """ELMS 6-hour LMGT3 round (Pro + Silver + Bronze)."""
    config = RaceConfig(
        race_name="ELMS — 6h Spa-Francorchamps (LMGT3)",
        race_duration_min=360.0,
        lap_time_sec=142.0,
        fuel_tank_liters=110.0,
        fuel_per_lap_liters=3.1,
        fuel_safety_laps=1,
        pit_loss_sec=48.0,
        formation_lap_min=6.0,
    )
    drivers = [
        Driver(name="Antoine Pro", category=DriverCategory.PRO, max_stint_min=120.0),
        Driver(
            name="Sophie Bronze",
            category=DriverCategory.BRONZE,
            min_stint_min=45.0,
            max_stint_min=65.0,
            min_total_drive_min=144.0,
        ),
        Driver(name="James Silver", category=DriverCategory.SILVER, max_stint_min=90.0),
    ]
    return config, drivers


def wec_hypercar_preset() -> tuple[RaceConfig, list[Driver]]:
    """WEC 6-hour Hypercar round (Pro + Pro + Bronze)."""
    config = RaceConfig(
        race_name="WEC — 6h Fuji (Hypercar)",
        race_duration_min=360.0,
        lap_time_sec=105.0,
        fuel_tank_liters=90.0,
        fuel_per_lap_liters=2.9,
        fuel_safety_laps=1,
        pit_loss_sec=42.0,
        formation_lap_min=5.0,
    )
    drivers = [
        Driver(name="Kamui Pro", category=DriverCategory.PRO, max_stint_min=120.0),
        Driver(
            name="Pietro Bronze",
            category=DriverCategory.BRONZE,
            min_stint_min=45.0,
            max_stint_min=65.0,
            min_total_drive_min=144.0,
        ),
        Driver(name="Jenson Pro", category=DriverCategory.PRO, max_stint_min=120.0),
    ]
    return config, drivers


PRESETS = {
    "fun-cup": fun_cup_preset,
    "elms": elms_lmgt3_preset,
    "wec": wec_hypercar_preset,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Endurance Race Stint Planner — fuel, driver rotation, "
            "pit windows, Safety Car re-plan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python endurance_stint_planner.py --preset fun-cup
  python endurance_stint_planner.py --preset elms --output outputs/elms.png
  python endurance_stint_planner.py --preset wec --safety-car 185 --extend-stint 8
  python endurance_stint_planner.py --race-hours 4 --lap-time 2:08 --tank 80 --fuel-per-lap 2.6
        """,
    )

    parser.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        help="Championship preset: fun-cup, elms, or wec.",
    )
    parser.add_argument("--race-hours", type=float, help="Race duration in hours.")
    parser.add_argument("--race-name", type=str, default="Custom Endurance Race")
    parser.add_argument("--lap-time", type=str, help="Lap time: seconds or M:SS.")
    parser.add_argument("--tank", type=float, help="Fuel tank capacity in litres.")
    parser.add_argument(
        "--fuel-per-lap",
        type=float,
        help="Fuel consumption per lap in litres.",
    )
    parser.add_argument(
        "--safety-laps",
        type=int,
        default=1,
        help="Fuel reserve laps kept in tank at pit entry.",
    )
    parser.add_argument(
        "--pit-loss",
        type=float,
        default=45.0,
        help="Pit stop time loss in seconds.",
    )
    parser.add_argument(
        "--drivers",
        type=str,
        help=(
            "Comma-separated driver specs: "
            "Name:Category:min_stint:max_stint:min_total_minutes"
        ),
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Show matplotlib stint timeline.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save timeline plot to this path.",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        help="Export stint table to CSV.",
    )
    parser.add_argument(
        "--safety-car",
        type=float,
        metavar="MINUTE",
        help="Re-plan from Safety Car deployment at this race minute.",
    )
    parser.add_argument(
        "--extend-stint",
        type=float,
        default=0.0,
        help="Minutes to extend current stint under SC before pitting.",
    )
    parser.add_argument(
        "--sc-pit-loss",
        type=float,
        default=25.0,
        help="Reduced pit loss under Safety Car (seconds).",
    )

    return parser


def parse_driver_spec(spec: str) -> Driver:
    """
    Parse 'Name:Category:min_stint:max_stint:min_total' driver string.
    Blank fields use defaults. Category: Pro, Silver, Bronze, or Amateur.
    """
    parts = [part.strip() for part in spec.strip().split(":")]
    if len(parts) < 2:
        raise ValueError(f"Invalid driver spec: {spec}")

    name = parts[0]
    if not name:
        raise ValueError(f"Driver name is required: {spec}")

    try:
        category = DriverCategory(parts[1])
    except ValueError as exc:
        valid = ", ".join(c.value for c in DriverCategory)
        raise ValueError(
            f"Invalid category '{parts[1]}' in {spec}. Use one of: {valid}."
        ) from exc

    min_stint = parse_optional_float(parts[2], 45.0) if len(parts) > 2 else 45.0
    max_stint = parse_optional_float(parts[3], 90.0) if len(parts) > 3 else 90.0
    min_total = parse_optional_float(parts[4], 0.0) if len(parts) > 4 else 0.0

    return Driver(
        name=name,
        category=category,
        min_stint_min=min_stint,
        max_stint_min=max_stint,
        min_total_drive_min=min_total,
    )


def config_from_args(args: argparse.Namespace) -> tuple[RaceConfig, list[Driver]]:
    if args.preset:
        return PRESETS[args.preset]()

    if not all([args.race_hours, args.lap_time, args.tank, args.fuel_per_lap]):
        raise ValueError(
            "Custom mode requires --race-hours, --lap-time, --tank, and "
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
        drivers = [parse_driver_spec(spec) for spec in args.drivers.split(",")]
    else:
        drivers = [
            Driver(name="Driver A", category=DriverCategory.PRO),
            Driver(
                name="Driver B",
                category=DriverCategory.BRONZE,
                min_total_drive_min=args.race_hours * 60 * 0.4,
            ),
        ]

    return config, drivers


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.preset and not args.race_hours:
        parser.print_help()
        print(
            "\nTip: start with  python endurance_stint_planner.py --preset fun-cup\n",
            file=sys.stderr,
        )
        return 1

    try:
        config, drivers = config_from_args(args)
    except (ValueError, KeyError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    planner = StintPlanner(config, drivers)
    plan = planner.build_plan()

    fuel_calc = FuelCalculator(config)
    print(
        f"\nFuel geometry: {fuel_calc.max_stint_laps()} laps/stint "
        f"({format_duration(fuel_calc.max_stint_minutes())})"
    )
    print(
        f"Lap time: {config.lap_time_sec:.3f}s  |  "
        f"Consumption: {config.fuel_per_lap_liters:.2f} L/lap  |  "
        f"Tank: {config.fuel_tank_liters:.0f} L"
    )

    if args.safety_car is not None:
        replanner = SafetyCarReplanner(
            config,
            drivers,
            sc_pit_loss_sec=args.sc_pit_loss,
        )
        plan = replanner.replan(
            plan,
            sc_deployed_min=args.safety_car,
            extend_current_stint_min=args.extend_stint,
        )
        print(
            f"\n[SC] Safety Car re-plan applied at "
            f"{format_duration(args.safety_car)}"
        )

    print_plan_table(plan)

    if args.export_csv:
        args.export_csv.parent.mkdir(parents=True, exist_ok=True)
        plan.to_dataframe().to_csv(args.export_csv, index=False)
        print(f"CSV exported to {args.export_csv}")

    if args.plot or args.output:
        if args.output and not args.plot:
            plt.switch_backend("Agg")
        plot_stint_timeline(
            plan,
            output_path=args.output,
            show=args.plot,
        )

    return 0


def run_self_tests() -> None:
    """Quick smoke tests for portfolio confidence (no external test runner)."""
    tests = [
        ["--preset", "fun-cup"],
        ["--preset", "elms"],
        ["--preset", "wec", "--safety-car", "185", "--extend-stint", "8"],
        [
            "--race-hours", "4",
            "--lap-time", "2:08",
            "--tank", "80",
            "--fuel-per-lap", "2.6",
            "--drivers", "A:Pro::90:0,B:Bronze:45:65:96",
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