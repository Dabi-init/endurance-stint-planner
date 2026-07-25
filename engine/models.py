"""Typed domain models for the Pitwall Agent strategy engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class DriverCategory(StrEnum):
    PRO = "Pro"
    SILVER = "Silver"
    BRONZE = "Bronze"


CATEGORY_COLORS = {
    DriverCategory.PRO: "#ff4d5f",
    DriverCategory.SILVER: "#75a7ff",
    DriverCategory.BRONZE: "#f5a65b",
}


def format_duration(minutes: float | None) -> str:
    """Format minutes as H:MM:SS for pit-wall readability."""
    if minutes is None or minutes < 0:
        return "0:00"
    total_seconds = round(minutes * 60)
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def format_duration_from_hours(hours: float) -> str:
    return format_duration(hours * 60.0)


def _driver_slug(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return value or "driver"


@dataclass
class Driver:
    name: str
    category: DriverCategory
    pace_delta_sec: float = 0.0
    driver_id: str = ""

    @property
    def id(self) -> str:
        return self.driver_id or _driver_slug(self.name)

    def lap_time_sec(
        self,
        base_lap_time_sec: float,
        fuel_save_pct: float = 0.0,
        fuel_save_pace_cost_sec_per_pct: float = 0.12,
    ) -> float:
        saving_cost = max(fuel_save_pct, 0.0) * max(
            fuel_save_pace_cost_sec_per_pct, 0.0
        )
        return max(base_lap_time_sec + self.pace_delta_sec + saving_cost, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "pace_delta_sec": self.pace_delta_sec,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int = 0) -> Driver:
        name = str(data.get("name", f"Driver {index + 1}"))
        return cls(
            name=name,
            category=DriverCategory(data.get("category", "Pro")),
            pace_delta_sec=float(data.get("pace_delta_sec", 0.0)),
            driver_id=str(data.get("id", "")).strip(),
        )


@dataclass
class DriverRegulations:
    """Configurable driver drive-time rules."""

    max_continuous_stint_min: float = 120.0
    pro_max_continuous_stint_min: float = 120.0
    silver_max_continuous_stint_min: float = 90.0
    bronze_max_continuous_stint_min: float = 65.0
    min_total_drive_min: float = 0.0
    max_total_drive_min: float = 0.0
    bronze_min_drive_min: float = 120.0
    silver_min_drive_min: float = 0.0
    fuel_safety_laps: int = 1
    change_tyres_every_stop: bool = True

    def max_stint_for_category(self, category: DriverCategory) -> float:
        if category == DriverCategory.BRONZE:
            return self.bronze_max_continuous_stint_min
        if category == DriverCategory.SILVER:
            return self.silver_max_continuous_stint_min
        return self.pro_max_continuous_stint_min

    def min_drive_for_category(self, category: DriverCategory) -> float:
        if category == DriverCategory.BRONZE:
            return self.bronze_min_drive_min
        if category == DriverCategory.SILVER:
            return self.silver_min_drive_min
        return self.min_total_drive_min

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_continuous_stint_min": self.max_continuous_stint_min,
            "pro_max_continuous_stint_min": self.pro_max_continuous_stint_min,
            "silver_max_continuous_stint_min": self.silver_max_continuous_stint_min,
            "bronze_max_continuous_stint_min": self.bronze_max_continuous_stint_min,
            "min_total_drive_min": self.min_total_drive_min,
            "max_total_drive_min": self.max_total_drive_min,
            "bronze_min_drive_min": self.bronze_min_drive_min,
            "silver_min_drive_min": self.silver_min_drive_min,
            "fuel_safety_laps": self.fuel_safety_laps,
            "change_tyres_every_stop": self.change_tyres_every_stop,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriverRegulations:
        return cls(
            max_continuous_stint_min=float(data.get("max_continuous_stint_min", 120.0)),
            pro_max_continuous_stint_min=float(
                data.get("pro_max_continuous_stint_min", 120.0)
            ),
            silver_max_continuous_stint_min=float(
                data.get("silver_max_continuous_stint_min", 90.0)
            ),
            bronze_max_continuous_stint_min=float(
                data.get("bronze_max_continuous_stint_min", 65.0)
            ),
            min_total_drive_min=float(data.get("min_total_drive_min", 0.0)),
            max_total_drive_min=float(data.get("max_total_drive_min", 0.0)),
            bronze_min_drive_min=float(data.get("bronze_min_drive_min", 120.0)),
            silver_min_drive_min=float(data.get("silver_min_drive_min", 0.0)),
            fuel_safety_laps=int(data.get("fuel_safety_laps", 1)),
            change_tyres_every_stop=bool(data.get("change_tyres_every_stop", True)),
        )


@dataclass
class RaceConfig:
    race_name: str
    race_duration_hours: float
    base_lap_time_sec: float
    fuel_tank_liters: float
    fuel_consumption_per_lap: float
    pit_stop_time_loss_sec: float
    refuel_rate_liters_per_sec: float
    tyre_life_laps: int
    tyre_change_time_sec: float
    drivers: list[Driver]
    regulations: DriverRegulations = field(default_factory=DriverRegulations)
    circuit_id: str = ""
    driver_change_time_sec: float = 18.0
    services_parallel: bool = True
    fuel_save_pace_cost_sec_per_pct: float = 0.12
    data_source: str = "Manual assumptions"

    def __post_init__(self) -> None:
        """Guarantee stable, unique driver identities even for direct construction."""
        self.ensure_unique_driver_ids()

    def ensure_unique_driver_ids(self) -> None:
        """Re-normalize identity after callers replace the mutable driver list."""
        seen_ids: dict[str, int] = {}
        unique_drivers: list[Driver] = []
        for driver in self.drivers:
            base_id = driver.driver_id or _driver_slug(driver.name)
            base_id = re.sub(r"-\d+$", "", base_id) if not driver.driver_id else base_id
            occurrence = seen_ids.get(base_id, 0) + 1
            seen_ids[base_id] = occurrence
            unique_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            unique_drivers.append(replace(driver, driver_id=unique_id))
        self.drivers = unique_drivers

    @property
    def race_duration_min(self) -> float:
        return max(self.race_duration_hours, 0.0) * 60.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_name": self.race_name,
            "race_duration_hours": self.race_duration_hours,
            "base_lap_time_sec": self.base_lap_time_sec,
            "fuel_tank_liters": self.fuel_tank_liters,
            "fuel_consumption_per_lap": self.fuel_consumption_per_lap,
            "pit_stop_time_loss_sec": self.pit_stop_time_loss_sec,
            "refuel_rate_liters_per_sec": self.refuel_rate_liters_per_sec,
            "tyre_life_laps": self.tyre_life_laps,
            "tyre_change_time_sec": self.tyre_change_time_sec,
            "driver_change_time_sec": self.driver_change_time_sec,
            "services_parallel": self.services_parallel,
            "fuel_save_pace_cost_sec_per_pct": (self.fuel_save_pace_cost_sec_per_pct),
            "drivers": [driver.to_dict() for driver in self.drivers],
            "regulations": self.regulations.to_dict(),
            "circuit_id": self.circuit_id,
            "data_source": self.data_source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RaceConfig:
        raw_drivers = data.get("drivers", [])
        drivers: list[Driver] = []
        seen_ids: dict[str, int] = {}
        for index, raw in enumerate(raw_drivers):
            driver = Driver.from_dict(raw, index=index)
            base_id = driver.id
            occurrence = seen_ids.get(base_id, 0) + 1
            seen_ids[base_id] = occurrence
            unique_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            drivers.append(replace(driver, driver_id=unique_id))

        regs = DriverRegulations.from_dict(data.get("regulations", {}))
        return cls(
            race_name=str(data.get("race_name", "Custom Race")),
            race_duration_hours=float(data.get("race_duration_hours", 6.0)),
            base_lap_time_sec=float(data.get("base_lap_time_sec", 120.0)),
            fuel_tank_liters=float(data.get("fuel_tank_liters", 100.0)),
            fuel_consumption_per_lap=float(data.get("fuel_consumption_per_lap", 2.9)),
            pit_stop_time_loss_sec=float(data.get("pit_stop_time_loss_sec", 55.0)),
            refuel_rate_liters_per_sec=float(
                data.get("refuel_rate_liters_per_sec", 2.5)
            ),
            tyre_life_laps=int(data.get("tyre_life_laps", 28)),
            tyre_change_time_sec=float(data.get("tyre_change_time_sec", 18.0)),
            driver_change_time_sec=float(data.get("driver_change_time_sec", 18.0)),
            services_parallel=bool(data.get("services_parallel", True)),
            fuel_save_pace_cost_sec_per_pct=float(
                data.get("fuel_save_pace_cost_sec_per_pct", 0.12)
            ),
            drivers=drivers,
            regulations=regs,
            circuit_id=str(data.get("circuit_id", "")),
            data_source=str(data.get("data_source", "Manual assumptions")),
        )


@dataclass
class Stint:
    stint_number: int
    driver: Driver
    start_min: float
    duration_min: float
    laps: int
    fuel_load_liters: float
    fuel_used_liters: float
    tyres_new: bool
    tyre_age_at_start_laps: int = 0
    limiting_factor: str = ""
    notes: str = ""
    fuel_added_liters: float = 0.0
    fuel_remaining_liters: float = 0.0
    pit_time_after_sec: float = 0.0
    tyre_set: int = 1

    @property
    def end_min(self) -> float:
        return self.start_min + self.duration_min

    @property
    def tyre_age_at_end_laps(self) -> int:
        return self.tyre_age_at_start_laps + self.laps

    def to_row(self) -> dict[str, Any]:
        return {
            "Stint": self.stint_number,
            "Driver": self.driver.name,
            "Category": self.driver.category.value,
            "Start": format_duration(self.start_min),
            "End": format_duration(self.end_min),
            "Duration": format_duration(self.duration_min),
            "Laps": self.laps,
            "Fuel start (L)": round(self.fuel_load_liters, 1),
            "Fuel added (L)": round(self.fuel_added_liters, 1),
            "Fuel used (L)": round(self.fuel_used_liters, 1),
            "Fuel remaining (L)": round(self.fuel_remaining_liters, 1),
            "Tyre set": self.tyre_set,
            "Tyre age end": self.tyre_age_at_end_laps,
            "Pit after (s)": round(self.pit_time_after_sec, 1),
            "Limit": self.limiting_factor or "-",
            "Notes": self.notes,
        }


@dataclass
class Infeasibility:
    code: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class PlanResult:
    config: RaceConfig
    stints: list[Stint] = field(default_factory=list)
    total_pit_stops: int = 0
    total_fuel_used_liters: float = 0.0
    predicted_laps: int = 0
    time_margin_at_flag_min: float = 0.0
    infeasibilities: list[Infeasibility] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_pit_time_sec: float = 0.0
    strategy_name: str = "Balanced"
    assumptions: list[str] = field(default_factory=list)
    source_summary: str = "Manual assumptions"

    @property
    def is_feasible(self) -> bool:
        return not self.infeasibilities and bool(self.stints)

    def driver_totals_by_id(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for stint in self.stints:
            totals[stint.driver.id] = (
                totals.get(stint.driver.id, 0.0) + stint.duration_min
            )
        return totals

    def driver_totals(self) -> dict[str, float]:
        """Return display totals without collapsing duplicate driver names."""
        name_counts: dict[str, int] = {}
        for driver in self.config.drivers:
            name_counts[driver.name] = name_counts.get(driver.name, 0) + 1

        by_id = self.driver_totals_by_id()
        totals: dict[str, float] = {}
        for driver in self.config.drivers:
            label = (
                driver.name
                if name_counts.get(driver.name, 0) == 1
                else f"{driver.name} [{driver.id}]"
            )
            totals[label] = by_id.get(driver.id, 0.0)
        return totals

    def stint_sheet_text(self) -> str:
        lines = [
            f"STINT SHEET — {self.config.race_name}",
            f"Strategy: {self.strategy_name}",
            f"Source: {self.source_summary}",
            (
                "Race duration: "
                f"{format_duration_from_hours(self.config.race_duration_hours)}"
            ),
            "-" * 96,
        ]
        for stint in self.stints:
            tyre_label = f"SET {stint.tyre_set}"
            lines.append(
                f"S{stint.stint_number:02d}  "
                f"{format_duration(stint.start_min):>8s} → "
                f"{format_duration(stint.end_min):<8s}  "
                f"{stint.driver.name:<16s}  {stint.laps:3d}L  "
                f"start {stint.fuel_load_liters:5.1f}L  "
                f"add {stint.fuel_added_liters:5.1f}L  "
                f"remain {stint.fuel_remaining_liters:4.1f}L  "
                f"{tyre_label:<7s}  [{stint.limiting_factor}]"
            )
            if stint.pit_time_after_sec:
                lines.append(
                    f"      PIT {stint.pit_time_after_sec:.1f}s after S"
                    f"{stint.stint_number:02d}"
                )
        lines.extend(
            [
                "-" * 96,
                (
                    f"Pit stops: {self.total_pit_stops}  |  "
                    f"Pit time: {self.total_pit_time_sec:.1f}s  |  "
                    f"Fuel used: {self.total_fuel_used_liters:.1f}L  |  "
                    f"Laps: {self.predicted_laps}  |  "
                    f"Margin: {format_duration(self.time_margin_at_flag_min)}"
                ),
            ]
        )
        if self.assumptions:
            lines.append("Assumptions:")
            lines.extend(f"- {item}" for item in self.assumptions)
        return "\n".join(lines)
