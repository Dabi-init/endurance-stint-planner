"""Compare a planned strategy with user-supplied actual results.

This is deliberately *not* a validation claim. The "actual" numbers are typed
in by a human and are not independently verified, so every report produced here
carries its provenance disclaimers and stays at Evidence Level C.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

PROVENANCE_DISCLAIMERS = [
    "User-supplied actual results — not independently validated.",
    "This comparison uses synthetic/user-supplied data. Not a validation claim "
    "unless real data and provenance are documented.",
    "Evidence Level C: the actual values below have no audited source attached.",
    "Pitwall Agent did not observe the race. It compares your typed numbers "
    "with its own pre-race plan and nothing else.",
]

EVIDENCE_LEVEL = "C"


class ValidationInputError(ValueError):
    """Raised when supplied actual results cannot be compared."""


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    unit: str
    planned: float | None
    actual: float | None
    difference: float | None
    deviation_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "unit": self.unit,
            "planned": self.planned,
            "actual": self.actual,
            "difference": self.difference,
            "deviation_pct": self.deviation_pct,
        }


def parse_stint_lengths(raw: str | None) -> list[int]:
    """Parse ``"18,19,17"`` into ``[18, 19, 17]`` with recoverable errors."""
    if raw is None or not raw.strip():
        return []
    values: list[int] = []
    for index, chunk in enumerate(raw.split(","), start=1):
        text = chunk.strip()
        if not text:
            continue
        try:
            number = float(text)
        except ValueError as exc:
            raise ValidationInputError(
                f"Stint {index} length must be a number of laps; got {text!r}."
            ) from exc
        if not math.isfinite(number):
            raise ValidationInputError(
                f"Stint {index} length must be finite; got {text!r}."
            )
        if number < 0 or abs(number - round(number)) > 1e-9:
            raise ValidationInputError(
                f"Stint {index} length must be a whole, non-negative lap count; "
                f"got {text!r}."
            )
        values.append(round(number))
    return values


def compare_metric(
    metric: str,
    unit: str,
    planned: float | None,
    actual: float | None,
) -> MetricComparison:
    """Compare one metric; deviation is relative to the planned value."""
    if planned is None or actual is None:
        return MetricComparison(metric, unit, planned, actual, None, None)
    difference = round(float(actual) - float(planned), 4)
    deviation = (
        None if float(planned) == 0.0 else round(difference / float(planned) * 100.0, 2)
    )
    return MetricComparison(metric, unit, planned, actual, difference, deviation)


def build_comparison(
    planned: dict[str, Any],
    actual: dict[str, Any],
) -> list[MetricComparison]:
    """Compare the metrics the user supplied against the stored plan."""
    rows = [
        compare_metric(
            "Laps completed", "laps", planned.get("laps"), actual.get("laps")
        ),
        compare_metric("Pit stops", "stops", planned.get("stops"), actual.get("stops")),
        compare_metric(
            "Fuel burn per lap",
            "litres/lap",
            planned.get("fuel_burn_per_lap"),
            actual.get("fuel_burn_per_lap"),
        ),
    ]
    planned_stints = planned.get("stint_lengths") or []
    actual_stints = actual.get("stint_lengths") or []
    if actual_stints:
        rows.append(
            compare_metric(
                "Stints run",
                "stints",
                float(len(planned_stints)) if planned_stints else None,
                float(len(actual_stints)),
            )
        )
        rows.append(
            compare_metric(
                "Mean stint length",
                "laps",
                (
                    round(sum(planned_stints) / len(planned_stints), 3)
                    if planned_stints
                    else None
                ),
                round(sum(actual_stints) / len(actual_stints), 3),
            )
        )
    return [row for row in rows if row.actual is not None]


def _stint_table(planned: list[int], actual: list[int]) -> list[str]:
    if not actual:
        return []
    lines = [
        "## Stint-by-stint laps",
        "",
        "| Stint | Planned laps | Actual laps | Difference |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for index in range(max(len(planned), len(actual))):
        planned_value = planned[index] if index < len(planned) else None
        actual_value = actual[index] if index < len(actual) else None
        difference = (
            actual_value - planned_value
            if planned_value is not None and actual_value is not None
            else None
        )
        lines.append(
            f"| {index + 1} | "
            f"{'-' if planned_value is None else planned_value} | "
            f"{'-' if actual_value is None else actual_value} | "
            f"{'-' if difference is None else f'{difference:+d}'} |"
        )
    lines.append("")
    return lines


def render_report(
    race_name: str,
    strategy: str,
    planned: dict[str, Any],
    actual: dict[str, Any],
    rows: list[MetricComparison],
    *,
    generated_at: datetime | None = None,
) -> str:
    """Render the Markdown comparison report, disclaimers included."""
    stamp = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# Plan versus reported result: {race_name}",
        "",
        f"- Generated: {stamp}",
        f"- Planned strategy: **{strategy}**",
        f"- Evidence Level: **{EVIDENCE_LEVEL}**",
        "",
        "## Data provenance",
        "",
        *[f"- {item}" for item in PROVENANCE_DISCLAIMERS],
        "",
        "## Planned versus actual",
        "",
        "| Metric | Unit | Planned | Actual (user-supplied) | Difference | Deviation |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        deviation = "-" if row.deviation_pct is None else f"{row.deviation_pct:+.2f}%"
        difference = "-" if row.difference is None else f"{row.difference:+g}"
        planned_text = "-" if row.planned is None else f"{row.planned:g}"
        lines.append(
            f"| {row.metric} | {row.unit} | {planned_text} | "
            f"{row.actual:g} | {difference} | {deviation} |"
        )
    lines.append("")
    lines.extend(
        _stint_table(
            list(planned.get("stint_lengths") or []),
            list(actual.get("stint_lengths") or []),
        )
    )
    lines.extend(
        [
            "## How to read this",
            "",
            "- Deviation is `(actual - planned) / planned`, expressed as a "
            "percentage of the planned value.",
            "- A deviation does not by itself mean the plan was wrong: the race "
            "conditions that produced the actual numbers are not recorded here.",
            "- To make this a real validation, attach the timing source, the "
            "session identifier, and who recorded the values.",
            "",
        ]
    )
    return "\n".join(lines)


def report_filename(generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"validation_{stamp}"
