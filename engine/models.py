"""Domain models for endurance stint planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DriverCategory(str, Enum):
    PRO = "Pro"
    SILVER = "Silver"
    BRONZE = "Bronze"


CATEGORY_COLORS = {
    DriverCategory.PRO: "#E10600",
    DriverCategory.SILVER: "#457B9D",
    DriverCategory.BRONZE: "#F4A261",
}


def format_duration(minutes: float) -> str:
    """Format minutes as H:MM:SS for pit-wall readability."""
    if minutes is None or minutes < 0:
        return "0:00"
    total_seconds = int(round(minutes * 60))
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def format_duration_from_hours(hours: float) -> str:
    return format_duration(hours * 60.0)


@dataclass
class Driver:
    name: str
    category: DriverCategory
    pace_delta_sec: float = 0.0

    def lap_time_sec(self, base_lap_time_sec: float) -> float:
        return max(base_lap_time_sec + self.pace_delta_sec, 1.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category.value,
            "pace_delta_sec": self.pace_delta_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Driver:
        return cls(
            name=str(data.get("name", "Driver")),
            category=DriverCategory(data.get("category", "Pro")),
            pace_delta_sec=float(data.get("pace_delta_sec", 0.0)),
        )


@dataclass
class DriverRegulations:
    """Configurable driver drive-time rules (GT endurance style)."""

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

    def to_dict(self) -> dict:
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
    def from_dict(cls, data: dict) -> DriverRegulations:
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

    @property
    def race_duration_min(self) -> float:
        return max(self.race_duration_hours, 0.0) * 60.0

    def to_dict(self) -> dict:
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
            "drivers": [d.to_dict() for d in self.drivers],
            "regulations": self.regulations.to_dict(),
            "circuit_id": self.circuit_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RaceConfig:
        drivers = [Driver.from_dict(d) for d in data.get("drivers", [])]
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
            tyre_change_time_sec=float(data.get("tyre_change_time_sec", 0.0)),
            drivers=drivers,
            regulations=regs,
            circuit_id=str(data.get("circuit_id", "")),
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

    @property
    def end_min(self) -> float:
        return self.start_min + self.duration_min

    @property
    def tyre_age_at_end_laps(self) -> int:
        return self.tyre_age_at_start_laps + self.laps

    def to_row(self) -> dict:
        return {
            "Stint": self.stint_number,
            "Driver": self.driver.name,
            "Category": self.driver.category.value,
            "Start": format_duration(self.start_min),
            "End": format_duration(self.end_min),
            "Duration": format_duration(self.duration_min),
            "Laps": self.laps,
            "Fuel Load (L)": round(self.fuel_load_liters, 1),
            "Fuel Used (L)": round(self.fuel_used_liters, 1),
            "Tyres": "New" if self.tyres_new else "Used",
            "Tyre Age End": self.tyre_age_at_end_laps,
            "Limit": self.limiting_factor or "-",
            "Notes": self.notes,
        }


@dataclass
class Infeasibility:
    code: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
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

    @property
    def is_feasible(self) -> bool:
        return len(self.infeasibilities) == 0 and len(self.stints) > 0

    def driver_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for stint in self.stints:
            totals[stint.driver.name] = (
                totals.get(stint.driver.name, 0.0) + stint.duration_min
            )
        return totals

    def stint_sheet_text(self) -> str:
        lines = [
            f"STINT SHEET — {self.config.race_name}",
            f"Race duration: {format_duration_from_hours(self.config.race_duration_hours)}",
            "-" * 72,
        ]
        for stint in self.stints:
            tyres = "NEW" if stint.tyres_new else "USED"
            lines.append(
                f"S{stint.stint_number:02d}  {format_duration(stint.start_min):>8s}"
                f" → {format_duration(stint.end_min):<8s}  "
                f"{stint.driver.name:<14s}  {stint.laps:3d}L  "
                f"{stint.fuel_load_liters:5.1f}L  {tyres}  [{stint.limiting_factor}]"
            )
        lines.append("-" * 72)
        lines.append(
            f"Pit stops: {self.total_pit_stops}  |  "
            f"Fuel: {self.total_fuel_used_liters:.1f} L  |  "
            f"Laps: {self.predicted_laps}  |  "
            f"Margin: {format_duration(self.time_margin_at_flag_min)}"
        )
        return "\n".join(lines)