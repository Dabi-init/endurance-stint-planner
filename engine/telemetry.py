"""Generic lap-telemetry ingestion with robust, inspectable calibration."""

from __future__ import annotations

import csv
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from io import StringIO
from itertools import pairwise
from typing import Any, TextIO

ALIASES: dict[str, tuple[str, ...]] = {
    "lap": ("lap", "lap_number", "lap_num", "lapindex"),
    "driver": ("driver", "driver_name", "pilot"),
    "lap_time_sec": (
        "lap_time_sec",
        "lap_time",
        "laptime",
        "last_lap_time",
        "time_sec",
    ),
    "fuel_remaining_liters": (
        "fuel_remaining_liters",
        "fuel_remaining",
        "fuel_level",
        "fuel_l",
        "fuel",
    ),
    "tyre_age_laps": (
        "tyre_age_laps",
        "tire_age_laps",
        "tyre_age",
        "tire_age",
        "tyre_laps",
        "tire_laps",
    ),
    "track_status": ("track_status", "status", "flag", "session_status"),
    "pit": ("pit", "in_pit", "is_pit", "pit_stop"),
}

GREEN_VALUES = {"", "green", "g", "clear", "racing", "1"}
TRUE_VALUES = {"1", "true", "yes", "y", "pit", "in"}


@dataclass(frozen=True)
class QualityFinding:
    severity: str
    message: str
    impact: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "message": self.message,
            "impact": self.impact,
        }


@dataclass
class TelemetryCalibration:
    source_name: str
    is_synthetic: bool
    rows_total: int
    rows_valid: int
    green_laps: int
    quality_score: int
    confidence: str
    evidence_level: str
    median_lap_time_sec: float | None = None
    lap_time_p10_sec: float | None = None
    lap_time_p90_sec: float | None = None
    fuel_burn_median_l_per_lap: float | None = None
    fuel_burn_p10_l_per_lap: float | None = None
    fuel_burn_p90_l_per_lap: float | None = None
    tyre_degradation_sec_per_lap: float | None = None
    driver_pace_deltas_sec: dict[str, float] = field(default_factory=dict)
    findings: list[QualityFinding] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list, repr=False)
    mapped_columns: dict[str, str] = field(default_factory=dict)

    @property
    def source_label(self) -> str:
        prefix = "Synthetic example" if self.is_synthetic else "Uploaded telemetry"
        return f"{prefix}: {self.source_name}"

    @property
    def usable_for_strategy(self) -> bool:
        return (
            self.median_lap_time_sec is not None
            and self.fuel_burn_median_l_per_lap is not None
            and self.quality_score >= 45
        )

    def config_patch(self) -> dict[str, float]:
        patch: dict[str, float] = {}
        if self.median_lap_time_sec is not None:
            patch["base_lap_time_sec"] = self.median_lap_time_sec
        if self.fuel_burn_median_l_per_lap is not None:
            patch["fuel_consumption_per_lap"] = self.fuel_burn_median_l_per_lap
        return patch

    def to_report(self) -> dict[str, Any]:
        return {
            "source": self.source_label,
            "synthetic": self.is_synthetic,
            "grain": "one row per completed car lap",
            "quality": {
                "score": self.quality_score,
                "confidence": self.confidence,
                "evidence_level": self.evidence_level,
                "rows_total": self.rows_total,
                "rows_valid": self.rows_valid,
                "green_laps": self.green_laps,
            },
            "calibration": {
                "median_lap_time_sec": self.median_lap_time_sec,
                "lap_time_p10_sec": self.lap_time_p10_sec,
                "lap_time_p90_sec": self.lap_time_p90_sec,
                "fuel_burn_median_l_per_lap": (self.fuel_burn_median_l_per_lap),
                "fuel_burn_p10_l_per_lap": self.fuel_burn_p10_l_per_lap,
                "fuel_burn_p90_l_per_lap": self.fuel_burn_p90_l_per_lap,
                "tyre_degradation_sec_per_lap": (self.tyre_degradation_sec_per_lap),
                "driver_pace_deltas_sec": self.driver_pace_deltas_sec,
            },
            "mapped_columns": self.mapped_columns,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def _normalise_header(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", " ").split())


def _map_headers(fieldnames: Iterable[str]) -> dict[str, str]:
    normalised = {_normalise_header(name): name for name in fieldnames}
    mapped: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                mapped[canonical] = normalised[alias]
                break
    return mapped


def _float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _lap_time_seconds(value: Any) -> float | None:
    direct = _float(value)
    if direct is not None:
        return direct
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    if len(values) == 2:
        return values[0] * 60.0 + values[1]
    return values[0] * 3600.0 + values[1] * 60.0 + values[2]


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _robust_filter(values: list[float]) -> list[float]:
    if len(values) < 5:
        return values
    q1 = _quantile(values, 0.25)
    q3 = _quantile(values, 0.75)
    if q1 is None or q3 is None:
        return values
    spread = q3 - q1
    lower = q1 - 1.5 * spread
    upper = q3 + 1.5 * spread
    return [value for value in values if lower <= value <= upper]


def _linear_slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 10:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator <= 1e-9:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator


def _read_text(source: str | bytes | TextIO) -> str:
    if hasattr(source, "read"):
        value = source.read()
    else:
        value = source
    if isinstance(value, bytes):
        return value.decode("utf-8-sig")
    return str(value)


def calibrate_telemetry(
    source: str | bytes | TextIO,
    *,
    source_name: str = "session.csv",
    is_synthetic: bool = False,
) -> TelemetryCalibration:
    """Profile, validate, and calibrate a generic one-row-per-lap CSV."""
    text = _read_text(source)
    reader = csv.DictReader(StringIO(text))
    headers = reader.fieldnames or []
    mapped = _map_headers(headers)
    raw_rows = list(reader)
    findings: list[QualityFinding] = []

    missing_core = [
        column for column in ("lap", "lap_time_sec") if column not in mapped
    ]
    if missing_core:
        findings.append(
            QualityFinding(
                "Critical",
                f"Missing required column(s): {', '.join(missing_core)}.",
                "Pace cannot be calibrated from this file.",
            )
        )
        return TelemetryCalibration(
            source_name,
            is_synthetic,
            len(raw_rows),
            0,
            0,
            0,
            "Insufficient",
            "C",
            findings=findings,
            mapped_columns=mapped,
        )

    records: list[dict[str, Any]] = []
    invalid_rows = 0
    for raw in raw_rows:
        lap_value = _float(raw.get(mapped["lap"]))
        lap_time = _lap_time_seconds(raw.get(mapped["lap_time_sec"]))
        if (
            lap_value is None
            or lap_time is None
            or lap_value < 0
            or lap_time <= 20
            or lap_time > 3600
        ):
            invalid_rows += 1
            continue
        status = str(raw.get(mapped.get("track_status", ""), "green")).strip().lower()
        record = {
            "lap": int(lap_value),
            "driver": str(raw.get(mapped.get("driver", ""), "Unknown")).strip()
            or "Unknown",
            "lap_time_sec": lap_time,
            "fuel_remaining_liters": _float(
                raw.get(mapped.get("fuel_remaining_liters", ""))
            ),
            "tyre_age_laps": _float(raw.get(mapped.get("tyre_age_laps", ""))),
            "track_status": status,
            "green": status in GREEN_VALUES,
            "pit": str(raw.get(mapped.get("pit", ""), "")).strip().lower()
            in TRUE_VALUES,
        }
        records.append(record)

    duplicate_laps = len(records) - len({record["lap"] for record in records})
    green_records = [
        record for record in records if record["green"] and not record["pit"]
    ]
    green_times = _robust_filter([record["lap_time_sec"] for record in green_records])

    fuel_deltas: list[float] = []
    ordered = sorted(records, key=lambda record: record["lap"])
    for previous, current in pairwise(ordered):
        previous_fuel = previous["fuel_remaining_liters"]
        current_fuel = current["fuel_remaining_liters"]
        if (
            previous_fuel is None
            or current_fuel is None
            or not previous["green"]
            or not current["green"]
            or previous["pit"]
            or current["pit"]
            or current["lap"] != previous["lap"] + 1
        ):
            continue
        delta = previous_fuel - current_fuel
        if 0.1 <= delta <= 15.0:
            fuel_deltas.append(delta)
    fuel_deltas = _robust_filter(fuel_deltas)

    driver_deltas: dict[str, float] = {}
    if green_times:
        overall = statistics.median(green_times)
        drivers = sorted({record["driver"] for record in green_records})
        for driver in drivers:
            driver_times = _robust_filter(
                [
                    record["lap_time_sec"]
                    for record in green_records
                    if record["driver"] == driver
                ]
            )
            if len(driver_times) >= 3:
                driver_deltas[driver] = round(
                    statistics.median(driver_times) - overall, 3
                )

    tyre_points = [
        (record["tyre_age_laps"], record["lap_time_sec"])
        for record in green_records
        if record["tyre_age_laps"] is not None
    ]
    tyre_slope = _linear_slope(tyre_points)

    total = len(raw_rows)
    valid = len(records)
    score = 100.0
    if total < 20:
        score -= 25
    if total < 8:
        score -= 20
    invalid_rate = invalid_rows / max(total, 1)
    duplicate_rate = duplicate_laps / max(valid, 1)
    score -= min(invalid_rate * 50.0, 35.0)
    score -= min(duplicate_rate * 50.0, 30.0)
    if len(green_times) < 10:
        score -= 25
    if len(fuel_deltas) < 5:
        score -= 25
    elif len(fuel_deltas) < 15:
        score -= 10
    if "driver" not in mapped:
        score -= 5
    if "tyre_age_laps" not in mapped:
        score -= 10
    score_int = round(min(max(score, 0.0), 100.0))

    if invalid_rows:
        findings.append(
            QualityFinding(
                "High" if invalid_rate > 0.1 else "Medium",
                (
                    f"{invalid_rows}/{max(total, 1)} rows "
                    f"({invalid_rate:.1%}) have invalid lap or lap-time values."
                ),
                "Those rows are excluded from every calibration.",
            )
        )
    if duplicate_laps:
        findings.append(
            QualityFinding(
                "High",
                (
                    f"{duplicate_laps}/{max(valid, 1)} valid rows "
                    f"({duplicate_rate:.1%}) duplicate a lap number."
                ),
                "Mixed car/session grain can bias pace and fuel estimates.",
            )
        )
    if "fuel_remaining_liters" not in mapped:
        findings.append(
            QualityFinding(
                "High",
                "No fuel-remaining column was mapped.",
                "Fuel consumption is withheld; the manual value remains active.",
            )
        )
    elif len(fuel_deltas) < 5:
        findings.append(
            QualityFinding(
                "High",
                f"Only {len(fuel_deltas)} usable consecutive fuel deltas exist.",
                "Fuel consumption is too weakly supported for strategy use.",
            )
        )
    if len(green_times) < 10:
        findings.append(
            QualityFinding(
                "High",
                f"Only {len(green_times)} representative green laps remain.",
                "The central pace estimate is unstable.",
            )
        )
    if tyre_slope is None:
        findings.append(
            QualityFinding(
                "Medium",
                "Tyre degradation could not be estimated from enough age variation.",
                "Tyre life stays a manual assumption.",
            )
        )
    if is_synthetic:
        findings.append(
            QualityFinding(
                "Low",
                "The bundled session is synthetic demonstration data.",
                "It proves the workflow, not real-world model validity.",
            )
        )

    if score_int >= 85 and len(green_times) >= 30 and len(fuel_deltas) >= 15:
        confidence = "High"
    elif score_int >= 65 and len(green_times) >= 15:
        confidence = "Medium"
    elif score_int >= 45:
        confidence = "Low"
    else:
        confidence = "Insufficient"
    evidence_level = (
        "C"
        if is_synthetic
        else (
            "A"
            if confidence == "High"
            else "B"
            if confidence in {"Medium", "Low"}
            else "C"
        )
    )

    fuel_supported = fuel_deltas if len(fuel_deltas) >= 5 else []
    return TelemetryCalibration(
        source_name=source_name,
        is_synthetic=is_synthetic,
        rows_total=total,
        rows_valid=valid,
        green_laps=len(green_times),
        quality_score=score_int,
        confidence=confidence,
        evidence_level=evidence_level,
        median_lap_time_sec=(statistics.median(green_times) if green_times else None),
        lap_time_p10_sec=_quantile(green_times, 0.10),
        lap_time_p90_sec=_quantile(green_times, 0.90),
        fuel_burn_median_l_per_lap=(
            statistics.median(fuel_supported) if fuel_supported else None
        ),
        fuel_burn_p10_l_per_lap=_quantile(fuel_supported, 0.10),
        fuel_burn_p90_l_per_lap=_quantile(fuel_supported, 0.90),
        tyre_degradation_sec_per_lap=tyre_slope,
        driver_pace_deltas_sec=driver_deltas,
        findings=findings,
        records=records,
        mapped_columns=mapped,
    )
