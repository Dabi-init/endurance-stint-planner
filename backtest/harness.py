"""Run the F1 planner against one recorded race and report the gap.

The bundled case is the 2024 Bahrain Grand Prix, car 1. Compound life, wear,
and pit-lane loss stay the event-file assumptions. The pace anchor is the
median clean lap from that same recorded session, so a small race-time gap is
not a blind pre-race forecast.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from engine.f1 import F1Plan, F1Setup, StintRequest, best_f1_plan, score_stints
from engine.series_config import IMAGE_POLICY, apply_overrides, load_setup
from historical.models import RaceActuals, race_actuals_from_dict

HONESTY = (
    "This is one recorded comparison, not a claim that the model is accurate. "
    "Compound life, degradation, and pit-lane loss are file assumptions. "
    "The pace anchor is this car's clean-lap median from the same race, "
    "so the time gap is not a blind pre-race forecast."
)

BUNDLED_FIXTURES = {
    "2024-r01-bahrain-verstappen": (
        Path(__file__).resolve().parent
        / "fixtures"
        / "2024_r01_bahrain_verstappen.json"
    ),
}


@dataclass(frozen=True)
class BacktestReport:
    event_name: str
    season: int
    round: int
    driver_number: int
    driver_code: str
    full_name: str
    team_name: str
    team_colour: str | None
    headshot_url: str | None
    livery_image_url: str | None
    actual_compounds: tuple[str, ...]
    actual_stint_laps: tuple[int, ...]
    actual_stop_laps: tuple[int, ...]
    actual_pit_durations_sec: tuple[float, ...]
    actual_race_time_sec: float | None
    predicted_compounds: tuple[str, ...]
    predicted_stint_laps: tuple[int, ...]
    predicted_stop_laps: tuple[int, ...]
    predicted_race_time_sec: float | None
    replay_race_time_sec: float | None
    race_time_delta_sec: float | None
    replay_time_delta_sec: float | None
    stop_count_delta: int
    same_stop_count: bool
    stint_length_deltas: tuple[int, ...] | None
    pace_anchor_sec: float | None
    evidence_level: str
    notes: tuple[str, ...]
    image_policy: str = IMAGE_POLICY

    def to_dict(self) -> dict[str, object]:
        return {
            "event_name": self.event_name,
            "season": self.season,
            "round": self.round,
            "driver_number": self.driver_number,
            "driver_code": self.driver_code,
            "full_name": self.full_name,
            "team_name": self.team_name,
            "team_colour": self.team_colour,
            "headshot_url": self.headshot_url,
            "livery_image_url": self.livery_image_url,
            "actual_compounds": list(self.actual_compounds),
            "actual_stint_laps": list(self.actual_stint_laps),
            "actual_stop_laps": list(self.actual_stop_laps),
            "actual_pit_durations_sec": list(self.actual_pit_durations_sec),
            "actual_race_time_sec": self.actual_race_time_sec,
            "predicted_compounds": list(self.predicted_compounds),
            "predicted_stint_laps": list(self.predicted_stint_laps),
            "predicted_stop_laps": list(self.predicted_stop_laps),
            "predicted_race_time_sec": self.predicted_race_time_sec,
            "replay_race_time_sec": self.replay_race_time_sec,
            "race_time_delta_sec": self.race_time_delta_sec,
            "replay_time_delta_sec": self.replay_time_delta_sec,
            "stop_count_delta": self.stop_count_delta,
            "same_stop_count": self.same_stop_count,
            "stint_length_deltas": (
                None
                if self.stint_length_deltas is None
                else list(self.stint_length_deltas)
            ),
            "pace_anchor_sec": self.pace_anchor_sec,
            "evidence_level": self.evidence_level,
            "notes": list(self.notes),
            "image_policy": self.image_policy,
        }


def load_actuals(path: Path) -> RaceActuals:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"The fixture is not valid JSON ({exc.msg}).") from exc
    return race_actuals_from_dict(payload)


def run_fixture(
    fixture_id: str | None = None, path: Path | None = None
) -> BacktestReport:
    if path is None:
        key = fixture_id or "2024-r01-bahrain-verstappen"
        if key not in BUNDLED_FIXTURES:
            known = ", ".join(sorted(BUNDLED_FIXTURES))
            raise ValueError(
                f"Unknown back-test fixture {key}. Known fixtures: {known}."
            )
        path = BUNDLED_FIXTURES[key]
    return run_backtest(load_actuals(path))


def run_backtest(actuals: RaceActuals, setup: F1Setup | None = None) -> BacktestReport:
    base = setup or load_setup(actuals.season, actuals.round)
    anchor: float | None = None
    if actuals.clean_lap_durations_sec:
        anchor = float(statistics.median(actuals.clean_lap_durations_sec))
        base = apply_overrides(base, {"base_lap_time_sec": anchor})
        base.provenance["base_lap_time_sec"] = "recorded-pace"
        base.assumptions.append(
            "Pace anchor is the median clean lap from this recorded session "
            f"({anchor:.3f} s). In-laps, out-laps, and lap 1 were left out."
        )
    plan = best_f1_plan(base)
    replay = score_stints(
        base,
        [StintRequest(stint.compound, stint.laps) for stint in actuals.stints],
        name="Recorded stints",
    )
    predicted_laps = tuple(plan.stint_laps)
    actual_laps = tuple(stint.laps for stint in actuals.stints)
    same = len(predicted_laps) == len(actual_laps) and bool(actual_laps)
    deltas = (
        tuple(
            left - right
            for left, right in zip(predicted_laps, actual_laps, strict=True)
        )
        if same
        else None
    )
    return BacktestReport(
        event_name=actuals.event_name,
        season=actuals.season,
        round=actuals.round,
        driver_number=actuals.driver_number,
        driver_code=actuals.driver_code,
        full_name=actuals.full_name,
        team_name=actuals.team_name,
        team_colour=actuals.team_colour,
        headshot_url=actuals.headshot_url,
        livery_image_url=actuals.livery_image_url,
        actual_compounds=tuple(stint.compound for stint in actuals.stints),
        actual_stint_laps=actual_laps,
        actual_stop_laps=actuals.stop_laps,
        actual_pit_durations_sec=actuals.pit_durations_sec,
        actual_race_time_sec=actuals.race_time_sec,
        predicted_compounds=tuple(plan.compounds_used),
        predicted_stint_laps=predicted_laps,
        predicted_stop_laps=tuple(plan.stop_laps),
        predicted_race_time_sec=plan.race_time_sec,
        replay_race_time_sec=replay.race_time_sec,
        race_time_delta_sec=_seconds_delta(plan.race_time_sec, actuals.race_time_sec),
        replay_time_delta_sec=_seconds_delta(
            replay.race_time_sec, actuals.race_time_sec
        ),
        stop_count_delta=plan.pit_stops - len(actuals.stop_laps),
        same_stop_count=len(plan.stop_laps) == len(actuals.stop_laps),
        stint_length_deltas=deltas,
        pace_anchor_sec=anchor,
        evidence_level=plan.evidence_level,
        notes=tuple(_notes(actuals, plan, replay, anchor)),
    )


def render(report: BacktestReport) -> str:
    lines = [
        f"{report.season} {report.event_name} — car {report.driver_number} {report.driver_code}",
        f"Recorded: {_pairs(report.actual_compounds, report.actual_stint_laps)}",
        f"Recorded stops: {_stop_text(report.actual_stop_laps)}",
        f"Predicted: {_pairs(report.predicted_compounds, report.predicted_stint_laps)}",
        f"Predicted stops: {_stop_text(report.predicted_stop_laps)}",
        f"Recorded race time: {_shown_time(report.actual_race_time_sec)}",
        f"Predicted race time: {_shown_time(report.predicted_race_time_sec)}",
        f"Predicted minus recorded: {_shown_delta(report.race_time_delta_sec)}",
        f"Recorded stints scored by the time model: {_shown_time(report.replay_race_time_sec)}",
        f"Evidence {report.evidence_level}",
    ]
    lines.extend(report.notes)
    return "\n".join(lines)


def _seconds_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return (round(left * 1000) - round(right * 1000)) / 1000


def _pairs(compounds: tuple[str, ...], laps: tuple[int, ...]) -> str:
    if not compounds:
        return "none"
    return ", ".join(
        f"{_label(compound)} {count}"
        for compound, count in zip(compounds, laps, strict=True)
    )


def _count(amount: int, singular: str) -> str:
    noun = singular if amount == 1 else f"{singular}s"
    return f"{amount} {noun}"


def _label(compound: str) -> str:
    return compound[:1].upper() + compound[1:].lower()


def _stop_text(laps: tuple[int, ...]) -> str:
    if not laps:
        return "no stop"
    if len(laps) == 1:
        return f"stop lap {laps[0]}"
    return "stop laps " + " and ".join(str(lap) for lap in laps)


def _shown_time(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    from engine.f1 import format_race_time

    return f"{format_race_time(seconds)} ({seconds:.3f} s)"


def _shown_delta(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    return f"{seconds:+.3f} s"


def _notes(
    actuals: RaceActuals,
    plan: F1Plan,
    replay: F1Plan,
    anchor: float | None,
) -> list[str]:
    notes = [HONESTY]
    if actuals.terms:
        notes.append(actuals.terms)
    for source in actuals.sources:
        notes.append(source)
    predicted = _pairs(tuple(plan.compounds_used), tuple(plan.stint_laps))
    recorded = _pairs(
        tuple(stint.compound for stint in actuals.stints),
        tuple(stint.laps for stint in actuals.stints),
    )
    notes.append(
        f"Predicted {_count(plan.pit_stops, 'stop')} ({predicted}), "
        f"{_stop_text(tuple(plan.stop_laps))}. "
        f"Recorded {_count(len(actuals.stop_laps), 'stop')} ({recorded}), "
        f"{_stop_text(actuals.stop_laps)}."
    )
    ages = [
        (index, stint.tyre_age_at_start)
        for index, stint in enumerate(actuals.stints, start=1)
        if stint.tyre_age_at_start
    ]
    if ages:
        index, age = ages[0]
        notes.append(
            f"Recorded tyre age at the start of stint {index} was {age}. "
            "The plan assumes new tyres."
        )
    if anchor is None:
        notes.append(
            "No clean-lap list was recorded, so the event-file base lap was used."
        )
    if replay.race_time_sec is None:
        notes.append("The recorded stints could not be scored with this file.")
    elif not replay.feasible:
        detail = (
            replay.infeasibilities[0].message
            if replay.infeasibilities
            else "Not legal."
        )
        notes.append(f"The recorded stints break a file rule. {detail}")
    return notes
