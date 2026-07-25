"""Field definitions and validation for guided beginner race configuration.

The prompting itself lives in the CLI; everything that can be wrong with a
value is decided here so it can be tested without a terminal.

Generic planning assumptions (safe ranges, preset defaults) are deliberately
kept separate from official regulations: this module never claims to encode any
series' sporting rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.models import Driver, DriverCategory, RaceConfig
from engine.planner import DEFAULT_PRESET, load_preset

PRESET_ORIGIN = "preset default"
USER_ORIGIN = "your input"

REGULATION_NOTICE = (
    "These are generic planning assumptions, not official regulations. "
    "Your event's sporting regulations always take precedence; enter them "
    "explicitly with `pitwall race set`."
)


class GuidedValueError(ValueError):
    """Raised for a recoverable, user-correctable configuration value."""


@dataclass(frozen=True)
class GuidedField:
    """One prompt: what it is, its unit, its safe band, and its fallback."""

    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    kind: str = "float"
    help_text: str = ""

    def unknown_hint(self, preset_value: Any) -> str:
        return (
            f"If you do not know it, press Enter to use the {DEFAULT_PRESET} "
            f"{PRESET_ORIGIN}: {preset_value:g} {self.unit}".rstrip()
        )

    def parse(self, raw: str) -> float | int:
        text = raw.strip()
        if not text:
            raise GuidedValueError(f"{self.label} needs a value in {self.unit}.")
        try:
            value = float(text)
        except ValueError as exc:
            raise GuidedValueError(
                f"{self.label} must be a number in {self.unit}; got {text!r}."
            ) from exc
        if value != value or value in (float("inf"), float("-inf")):
            raise GuidedValueError(f"{self.label} must be a finite number.")
        if self.kind == "int" and abs(value - round(value)) > 1e-9:
            raise GuidedValueError(
                f"{self.label} must be a whole number of {self.unit}."
            )
        if value < self.minimum or value > self.maximum:
            raise GuidedValueError(
                f"{self.label} must be between {self.minimum:g} and "
                f"{self.maximum:g} {self.unit}; got {value:g}."
            )
        return round(value) if self.kind == "int" else value


GUIDED_FIELDS: list[GuidedField] = [
    GuidedField(
        "race_duration_hours",
        "Race duration",
        "hours",
        0.25,
        48.0,
        help_text="Scheduled length of the race, from green flag to chequered.",
    ),
    GuidedField(
        "base_lap_time_sec",
        "Representative green lap time",
        "seconds",
        20.0,
        900.0,
        help_text="A realistic race lap, not a qualifying lap.",
    ),
    GuidedField(
        "fuel_consumption_per_lap",
        "Fuel burn per lap",
        "litres/lap",
        0.05,
        60.0,
        help_text="Average green-running consumption for one lap.",
    ),
    GuidedField(
        "fuel_tank_liters",
        "Usable fuel tank",
        "litres",
        1.0,
        250.0,
        help_text="Fuel you can actually use, after any mandated restriction.",
    ),
    GuidedField(
        "tyre_life_laps",
        "Tyre life",
        "laps",
        1,
        200,
        kind="int",
        help_text="How many laps you are willing to run one set of tyres.",
    ),
    GuidedField(
        "driver_count",
        "Number of drivers",
        "drivers",
        1,
        8,
        kind="int",
        help_text="Drivers sharing the car, including the starting driver.",
    ),
    GuidedField(
        "min_driver_time_min",
        "Minimum drive time per sharing driver",
        "minutes",
        0,
        1440,
        help_text=(
            "Minimum total minutes a non-Pro driver must complete. Enter 0 if "
            "your event does not require one."
        ),
    ),
]

FIELDS_BY_KEY = {field.key: field for field in GUIDED_FIELDS}


def preset_defaults(preset: str = DEFAULT_PRESET) -> dict[str, Any]:
    """Fallback values, clearly attributable to a bundled preset."""
    config = load_preset(preset)
    return {
        "race_duration_hours": config.race_duration_hours,
        "base_lap_time_sec": config.base_lap_time_sec,
        "fuel_consumption_per_lap": config.fuel_consumption_per_lap,
        "fuel_tank_liters": config.fuel_tank_liters,
        "tyre_life_laps": config.tyre_life_laps,
        "driver_count": max(len(config.drivers), 1),
        "min_driver_time_min": config.regulations.bronze_min_drive_min,
    }


def parse_field(key: str, raw: str, preset_value: Any) -> tuple[Any, str]:
    """Return ``(value, origin)`` for one answered prompt.

    An empty answer accepts the preset default and is labelled as such.
    """
    field = FIELDS_BY_KEY.get(key)
    if field is None:
        raise GuidedValueError(f"Unknown configuration field: {key}")
    if not raw.strip():
        return preset_value, PRESET_ORIGIN
    return field.parse(raw), USER_ORIGIN


def cross_check(values: dict[str, Any]) -> list[str]:
    """Return recoverable problems that only appear once fields are combined."""
    problems: list[str] = []
    burn = float(values.get("fuel_consumption_per_lap", 0.0))
    tank = float(values.get("fuel_tank_liters", 0.0))
    if burn > 0 and tank > 0 and burn > tank:
        problems.append(
            f"Fuel burn ({burn:g} litres/lap) is larger than the usable tank "
            f"({tank:g} litres): the car could not complete a single lap. "
            "Check the units on both values."
        )
    if burn > 0 and tank > 0 and tank / burn < 2:
        problems.append(
            f"The usable tank only covers {tank / burn:.1f} laps. Confirm the "
            "tank size and burn rate before planning stints."
        )
    duration_min = float(values.get("race_duration_hours", 0.0)) * 60.0
    drivers = int(values.get("driver_count", 1) or 1)
    minimum = float(values.get("min_driver_time_min", 0.0))
    if minimum > 0 and drivers * minimum > duration_min:
        problems.append(
            f"{drivers} driver(s) x {minimum:g} minutes exceeds the "
            f"{duration_min:g}-minute race. Reduce the minimum drive time or "
            "the driver count."
        )
    lap_time = float(values.get("base_lap_time_sec", 0.0))
    tyre_life = float(values.get("tyre_life_laps", 0.0))
    if lap_time > 0 and duration_min > 0 and lap_time > duration_min * 60.0:
        problems.append(
            f"A {lap_time:g}-second lap is longer than the whole race. Check "
            "whether the duration was entered in hours."
        )
    if tyre_life <= 0:
        problems.append("Tyre life must be at least one lap.")
    return problems


def build_race_config(
    values: dict[str, Any],
    *,
    preset: str = DEFAULT_PRESET,
    race_name: str = "",
) -> RaceConfig:
    """Turn validated guided answers into a full race configuration.

    Values that were never asked about keep their bundled-preset value, so the
    resulting race is always complete and auditable.
    """
    problems = cross_check(values)
    if problems:
        raise GuidedValueError(" ".join(problems))
    config = load_preset(preset)
    config.race_name = race_name.strip() or f"Guided race ({preset} baseline)"
    config.race_duration_hours = float(values["race_duration_hours"])
    config.base_lap_time_sec = float(values["base_lap_time_sec"])
    config.fuel_consumption_per_lap = float(values["fuel_consumption_per_lap"])
    config.fuel_tank_liters = float(values["fuel_tank_liters"])
    config.tyre_life_laps = int(values["tyre_life_laps"])
    config.regulations.bronze_min_drive_min = float(values["min_driver_time_min"])
    config.drivers = _drivers_for(int(values["driver_count"]), config.drivers)
    config.ensure_unique_driver_ids()
    config.data_source = "Manual assumptions (guided setup)"
    return config


def _drivers_for(count: int, existing: list[Driver]) -> list[Driver]:
    count = max(int(count), 1)
    drivers = [
        Driver(driver.name, driver.category, driver.pace_delta_sec)
        for driver in existing[:count]
    ]
    while len(drivers) < count:
        index = len(drivers) + 1
        category = DriverCategory.PRO if index == 1 else DriverCategory.SILVER
        drivers.append(Driver(f"Driver {index}", category, 0.0))
    return drivers


def summary_rows(values: dict[str, Any], origins: dict[str, str]) -> list[list[str]]:
    """Rows of ``[field, value, unit, origin]`` for the confirmation screen."""
    rows: list[list[str]] = []
    for field in GUIDED_FIELDS:
        value = values.get(field.key)
        rows.append(
            [
                field.label,
                f"{value:g}" if isinstance(value, (int, float)) else str(value),
                field.unit,
                origins.get(field.key, PRESET_ORIGIN),
            ]
        )
    return rows
