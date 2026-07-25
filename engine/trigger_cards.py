"""Deterministic strategy trigger cards for pre-race race-day preparation.

A trigger card answers two questions for the crew before the race starts:

1. Which single observation would invalidate part of the recommended plan?
2. What is the pre-agreed action when that observation crosses its threshold?

Every value here is derived from the deterministic planner output and the same
uncertainty bounds used by the strategy comparison. No card invents a number,
and no card claims live race knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.models import PlanResult
from engine.simulation import UncertaintyModel

MANUAL_SOURCE = "manual"
TELEMETRY_SOURCE = "telemetry"

HOLD = "HOLD"
RECONSIDER = "RECONSIDER"

PRE_RACE_NOTICE = (
    "Pre-race trigger cards only. Pitwall Agent has no live timing or race "
    "control feed; a human must make the observation and the final call."
)


@dataclass(frozen=True)
class TriggerObservation:
    """Optional observed values used to evaluate a card against its thresholds.

    All fields default to ``None``, in which case the planned value from the
    deterministic engine is used and the card reports ``HOLD``.
    """

    fuel_burn_per_lap: float | None = None
    green_lap_time_sec: float | None = None
    tyre_life_laps: float | None = None
    safety_car_window_min: tuple[float, float] | None = None


@dataclass(frozen=True)
class TriggerCard:
    """One observable metric, its agreed thresholds, and the agreed actions."""

    id: str
    name: str
    source: str
    metric: str
    unit: str
    threshold_low: float | None
    threshold_high: float | None
    current_value: float
    affected_decision: str
    action_hold: str
    action_reconsider: str
    status: str
    notes: list[str] = field(default_factory=list)

    @property
    def action(self) -> str:
        return self.action_hold if self.status == HOLD else self.action_reconsider

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "metric": self.metric,
            "unit": self.unit,
            "threshold_low": self.threshold_low,
            "threshold_high": self.threshold_high,
            "current_value": self.current_value,
            "affected_decision": self.affected_decision,
            "action_hold": self.action_hold,
            "action_reconsider": self.action_reconsider,
            "status": self.status,
            "notes": list(self.notes),
        }


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


def _bounds(low: float, high: float) -> tuple[float, float]:
    """Return ``(lower, upper)`` without assuming which percentile is larger."""
    return (low, high) if low <= high else (high, low)


def _longest_planned_tyre_run(plan: PlanResult) -> int:
    """Laps the most-used tyre set must survive in the planned stint sequence."""
    if not plan.stints:
        return 0
    return max(stint.tyre_age_at_end_laps for stint in plan.stints)


def _planned_stop_times_min(plan: PlanResult) -> list[float]:
    """Scheduled race-clock minutes at which the plan enters the pit lane."""
    return [
        round(stint.end_min, 2)
        for stint in plan.stints[:-1]
        if stint.pit_time_after_sec > 0
    ]


def _fuel_cards(
    plan: PlanResult,
    uncertainty: UncertaintyModel,
    observation: TriggerObservation,
    source: str,
) -> list[TriggerCard]:
    low, high = _bounds(uncertainty.fuel_p10_l_per_lap, uncertainty.fuel_p90_l_per_lap)
    planned = plan.config.fuel_consumption_per_lap
    observed = (
        planned
        if observation.fuel_burn_per_lap is None
        else observation.fuel_burn_per_lap
    )
    return [
        TriggerCard(
            id="FUEL_BURN_HIGH",
            name="Fuel burn above the modelled range",
            source=source,
            metric="fuel_burn_per_lap",
            unit="litres/lap",
            threshold_low=None,
            threshold_high=_round(high),
            current_value=round(float(observed), 3),
            affected_decision="Stint length, fuel addition per stop",
            action_hold=(
                "Hold the planned stint lengths and fuel additions; burn is "
                "inside the modelled range."
            ),
            action_reconsider=(
                "Shorten the affected stint and increase fuel addition at the "
                "next stop, then re-run `pitwall compare`."
            ),
            status=RECONSIDER if observed > high else HOLD,
            notes=[
                f"Modelled burn range {low:.3f}–{high:.3f} litres/lap "
                f"(planned {planned:.3f})."
            ],
        ),
        TriggerCard(
            id="FUEL_BURN_LOW",
            name="Fuel burn below the modelled range",
            source=source,
            metric="fuel_burn_per_lap",
            unit="litres/lap",
            threshold_low=_round(low),
            threshold_high=None,
            current_value=round(float(observed), 3),
            affected_decision="Stint length, fuel addition per stop",
            action_hold=(
                "Hold the planned fuel additions; burn is inside the modelled range."
            ),
            action_reconsider=(
                "A longer stint may now be possible: reduce fuel addition only "
                "after re-running `pitwall compare` with the measured burn."
            ),
            status=RECONSIDER if observed < low else HOLD,
            notes=[
                f"Modelled burn range {low:.3f}–{high:.3f} litres/lap "
                f"(planned {planned:.3f})."
            ],
        ),
    ]


def _pace_cards(
    plan: PlanResult,
    uncertainty: UncertaintyModel,
    observation: TriggerObservation,
    source: str,
) -> list[TriggerCard]:
    low, high = _bounds(uncertainty.pace_p10_sec, uncertainty.pace_p90_sec)
    planned = plan.config.base_lap_time_sec
    observed = (
        planned
        if observation.green_lap_time_sec is None
        else observation.green_lap_time_sec
    )
    range_note = (
        f"Modelled green lap range {low:.3f} s (P10, optimistic/faster) to "
        f"{high:.3f} s (P90, pessimistic/slower); planned {planned:.3f} s."
    )
    return [
        TriggerCard(
            id="PACE_SLOW",
            name="Green lap time slower than the pessimistic bound",
            source=source,
            metric="green_lap_time_sec",
            unit="seconds/lap",
            threshold_low=None,
            threshold_high=_round(high),
            current_value=round(float(observed), 3),
            affected_decision="Stint lengths, stop timing, lap count at the flag",
            action_hold="Hold the planned stop windows; pace is inside the range.",
            action_reconsider=(
                "Lap count at the flag will drop: re-time the remaining stops "
                "with `pitwall plan` before committing to the next window."
            ),
            status=RECONSIDER if observed > high else HOLD,
            notes=[range_note],
        ),
        TriggerCard(
            id="PACE_FAST",
            name="Green lap time faster than the optimistic bound",
            source=source,
            metric="green_lap_time_sec",
            unit="seconds/lap",
            threshold_low=_round(low),
            threshold_high=None,
            current_value=round(float(observed), 3),
            affected_decision="Stint lengths, stop timing, lap count at the flag",
            action_hold="Hold the planned stop windows; pace is inside the range.",
            action_reconsider=(
                "More laps per stint are being completed than planned: re-time "
                "the remaining stops with `pitwall plan` before the next window."
            ),
            status=RECONSIDER if observed < low else HOLD,
            notes=[range_note],
        ),
    ]


def _tyre_card(
    plan: PlanResult,
    observation: TriggerObservation,
    source: str,
) -> TriggerCard:
    required_laps = _longest_planned_tyre_run(plan)
    planned_life = float(plan.config.tyre_life_laps)
    observed = (
        planned_life
        if observation.tyre_life_laps is None
        else float(observation.tyre_life_laps)
    )
    return TriggerCard(
        id="TYRE_LIFE_LOW",
        name="Usable tyre life below the planned longest run",
        source=source,
        metric="tyre_life_laps",
        unit="laps",
        threshold_low=float(required_laps),
        threshold_high=None,
        current_value=round(float(observed), 1),
        affected_decision="Number of tyre changes, pit service time per stop",
        action_hold=(
            "Hold the planned tyre allocation; the longest planned run fits "
            "inside the configured tyre life."
        ),
        action_reconsider=(
            "The planned longest run no longer fits the tyre: add a tyre "
            "change at the next stop and re-run `pitwall plan`."
        ),
        status=RECONSIDER if observed < required_laps else HOLD,
        notes=[
            f"Longest planned run on one tyre set is {required_laps} laps; "
            f"configured tyre life is {planned_life:g} laps."
        ],
    )


def _safety_car_card(
    plan: PlanResult,
    observation: TriggerObservation,
    source: str,
) -> TriggerCard:
    stop_times = _planned_stop_times_min(plan)
    window = observation.safety_car_window_min
    notes = [
        "PRE-RACE WHAT-IF ONLY: Pitwall Agent does not receive live race "
        "control data and cannot predict actual Safety Car events.",
        (
            "Planned stop times (race minutes): "
            + (", ".join(f"{value:g}" for value in stop_times) or "none")
        ),
    ]
    if window is None:
        return TriggerCard(
            id="SAFETY_CAR_WINDOW",
            name="Safety Car overlaps a planned stop",
            source=source,
            metric="safety_car_window_min",
            unit="race minutes",
            threshold_low=None,
            threshold_high=None,
            current_value=stop_times[0] if stop_times else 0.0,
            affected_decision="Stop timing, pit-lane time loss captured under SC",
            action_hold=(
                "No Safety Car window has been declared for this plan; hold the "
                "planned stop times."
            ),
            action_reconsider=(
                "Declare a window with `pitwall scenario DEPLOY DURATION` to see "
                "the modelled effect on the planned stops."
            ),
            status=HOLD,
            notes=[*notes, "No Safety Car window declared."],
        )
    start, end = _bounds(window[0], window[1])
    overlapping = [value for value in stop_times if start <= value <= end]
    return TriggerCard(
        id="SAFETY_CAR_WINDOW",
        name="Safety Car overlaps a planned stop",
        source=source,
        metric="safety_car_window_min",
        unit="race minutes",
        threshold_low=_round(start, 2),
        threshold_high=_round(end, 2),
        current_value=(
            overlapping[0] if overlapping else (stop_times[0] if stop_times else 0.0)
        ),
        affected_decision="Stop timing, pit-lane time loss captured under SC",
        action_hold=(
            "The declared window does not overlap a planned stop; hold the "
            "planned stop times."
        ),
        action_reconsider=(
            "A planned stop falls inside the declared window: take the stop "
            "under the Safety Car to capture the reduced pit-lane loss."
        ),
        status=RECONSIDER if overlapping else HOLD,
        notes=[
            *notes,
            f"Declared Safety Car window: {start:g}–{end:g} race minutes.",
        ],
    )


def build_trigger_cards(
    plan: PlanResult,
    uncertainty: UncertaintyModel,
    observation: TriggerObservation | None = None,
    *,
    telemetry_calibrated: bool = False,
) -> list[TriggerCard]:
    """Build the deterministic trigger cards for one recommended plan.

    Args:
        plan: The deterministic plan for the recommended strategy.
        uncertainty: The pace and fuel bounds used by the same comparison.
        observation: Optional user-observed values to test against thresholds.
        telemetry_calibrated: ``True`` when the inputs came from telemetry.
    """
    observed = observation or TriggerObservation()
    source = TELEMETRY_SOURCE if telemetry_calibrated else MANUAL_SOURCE
    cards = [
        *_fuel_cards(plan, uncertainty, observed, source),
        *_pace_cards(plan, uncertainty, observed, source),
        _tyre_card(plan, observed, source),
        _safety_car_card(plan, observed, source),
    ]
    return cards


def trigger_cards_payload(
    plan: PlanResult,
    uncertainty: UncertaintyModel,
    observation: TriggerObservation | None = None,
    *,
    telemetry_calibrated: bool = False,
) -> list[dict[str, Any]]:
    """Return trigger cards as plain dictionaries for JSON and Markdown output."""
    return [
        card.to_dict()
        for card in build_trigger_cards(
            plan,
            uncertainty,
            observation,
            telemetry_calibrated=telemetry_calibrated,
        )
    ]


def trigger_cards_markdown(cards: list[dict[str, Any]]) -> list[str]:
    """Render trigger cards as Markdown lines for the pit sheet."""
    lines = [
        "## Trigger cards — what to watch and what to do",
        "",
        f"> {PRE_RACE_NOTICE}",
        "",
        "| Trigger | Source | Metric | Watch band | Planned/observed | Status |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for card in cards:
        low = card["threshold_low"]
        high = card["threshold_high"]
        if low is not None and high is not None:
            band = f"{low:g} to {high:g}"
        elif high is not None:
            band = f"above {high:g} triggers"
        elif low is not None:
            band = f"below {low:g} triggers"
        else:
            band = "not declared"
        lines.append(
            f"| {card['id']} | {card['source']} | {card['metric']} ({card['unit']}) "
            f"| {band} | {card['current_value']:g} | **{card['status']}** |"
        )
    lines.append("")
    for card in cards:
        lines.extend(
            [
                f"### {card['id']} — {card['name']}",
                "",
                f"- Affects: {card['affected_decision']}",
                f"- If inside the band (HOLD): {card['action_hold']}",
                f"- If the threshold is crossed (RECONSIDER): "
                f"{card['action_reconsider']}",
                *[f"- Note: {note}" for note in card["notes"]],
                "",
            ]
        )
    return lines
