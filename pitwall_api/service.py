"""Map HTTP bodies onto the deterministic engine. No race maths lives here."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from engine.f1 import (
    DISCLAIMER,
    UNCERTAINTY,
    F1Plan,
    F1Setup,
    SafetyCarRequest,
    ScenarioRequest,
    StintRequest,
    best_f1_plan,
    compare_f1,
    readiness_gaps,
    replan_f1_safety_car,
    score_stints,
)
from engine.f1_odds import race_time_odds, undercut
from engine.models import PlanResult, RaceConfig
from engine.planner import PlanOptions, compute_plan, list_presets, load_preset
from engine.safety_car import SafetyCarConfig, replan_with_safety_car
from engine.series_config import (
    IMAGE_POLICY,
    apply_overrides,
    colour_css,
    load_setup,
    setup_from_dict,
    setup_to_dict,
)
from engine.strategy import compare_strategies
from engine.telemetry import calibrate_telemetry
from historical.errors import HistoricalSourceError
from historical.terms import JOLPICA_TERMS, OPENF1_TERMS
from live.wec import WEC_NOTICE
from pitwall_api.schemas import (
    ClassesRequest,
    ClassesResponse,
    ClassPlanOut,
    CompareRequest,
    CompareResponse,
    DeclaredWeatherRequest,
    DeclaredWeatherResponse,
    DriverCard,
    EnduranceOptionsIn,
    IssueOut,
    OddsRequest,
    PlanRequest,
    PlanResponse,
    PrepareRequest,
    PrepareResponse,
    RuleOut,
    SafetyCarRequestIn,
    SafetyCarResponse,
    SheetRequest,
    SheetResponse,
    SimulationOut,
    StintOut,
    TeamCard,
    TelemetryRequest,
    UndercutRequest,
)


class RequestError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def create_plan(body: PlanRequest) -> PlanResponse:
    if body.series == "f1":
        setup = _f1_setup(body.season, body.round, body.setup, body.overrides)
        if body.strategy:
            plan = score_stints(
                setup,
                [StintRequest(row.compound, row.laps) for row in body.strategy],
                name="Custom",
            )
        else:
            plan = best_f1_plan(setup)
        return _f1_plan(plan, body.detail)
    config = _endurance_config(body.race)
    options = _options(body.options)
    return _endurance_plan(compute_plan(config, options), body.detail, options)


def compare(body: CompareRequest) -> CompareResponse:
    if body.series == "f1":
        setup = _f1_setup(body.season, body.round, body.setup, body.overrides)
        scenarios = [
            ScenarioRequest(
                row.name,
                None
                if row.stints is None
                else tuple(
                    StintRequest(stint.compound, stint.laps) for stint in row.stints
                ),
            )
            for row in body.scenarios
        ]
        plans = compare_f1(setup, scenarios)
        return CompareResponse(
            series="f1",
            scenarios=[_f1_plan(plan, body.detail) for plan in plans],
            image_policy=IMAGE_POLICY,
            disclaimer=DISCLAIMER,
        )
    config = _endurance_config(body.race)
    comparison = compare_strategies(config)
    return CompareResponse(
        series="endurance",
        scenarios=[
            _endurance_plan(
                outcome.plan,
                body.detail,
                outcome.options,
                simulation=SimulationOut(
                    laps_p10=outcome.simulation.laps_p10,
                    laps_median=outcome.simulation.laps_median,
                    laps_p90=outcome.simulation.laps_p90,
                    extra_stop_probability=outcome.simulation.extra_stop_probability,
                    source=outcome.simulation.source,
                    confidence=outcome.simulation.confidence,
                ),
                rank=outcome.rank,
                preferred=outcome.preferred,
                ranking_reason=outcome.ranking_reason,
                strategy_name=outcome.name,
            )
            for outcome in comparison.outcomes
        ],
        image_policy=IMAGE_POLICY,
        disclaimer=DISCLAIMER,
    )


def safety_car(body: SafetyCarRequestIn) -> SafetyCarResponse:
    if body.series == "f1":
        setup = _f1_setup(body.season, body.round, body.setup, body.overrides)
        if body.strategy:
            plan = score_stints(
                setup,
                [StintRequest(row.compound, row.laps) for row in body.strategy],
                name="Custom",
            )
        else:
            plan = best_f1_plan(setup)
        window = body.safety_car
        try:
            request = SafetyCarRequest(
                start_lap=int(window["start_lap"]),
                end_lap=int(window["end_lap"]),
                pit_loss_sec=float(window["pit_loss_sec"]),
                pull_pit_into_sc=bool(window.get("pull_pit_into_sc", True)),
                field_lap_delta_sec=float(window.get("field_lap_delta_sec", 0.0)),
                rival_stops=int(window.get("rival_stops", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RequestError(
                "F1 safety_car needs start_lap, end_lap, and pit_loss_sec."
            ) from exc
        result = replan_f1_safety_car(plan, request)
        return SafetyCarResponse(
            series="f1",
            summary=result.summary,
            confidence=result.confidence,
            time_saved_sec=result.time_saved_sec,
            stop_laps=list(result.stop_laps),
            stops_moved=result.stops_moved,
            notes=list(result.assumptions),
            original=_f1_plan(result.original, body.detail),
            replanned=_f1_plan(result.replanned, body.detail),
            disclaimer=DISCLAIMER,
        )
    config = _endurance_config(body.race)
    options = _options(body.options)
    original = compute_plan(config, options)
    window = body.safety_car
    try:
        scenario = SafetyCarConfig(
            deploy_min=float(window["deploy_min"]),
            duration_min=float(window["duration_min"]),
            lap_time_multiplier=float(window.get("lap_time_multiplier", 1.4)),
            sc_pit_loss_sec=float(window.get("sc_pit_loss_sec", 25.0)),
            pull_pit_into_sc=bool(window.get("pull_pit_into_sc", True)),
            fuel_burn_multiplier=float(window.get("fuel_burn_multiplier", 0.55)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RequestError(
            "Endurance safety_car needs deploy_min and duration_min."
        ) from exc
    race_end = config.race_duration_min
    if scenario.deploy_min < 0:
        raise RequestError(
            f"deploy_min {scenario.deploy_min:g} must be zero or higher.",
            status=422,
        )
    if scenario.deploy_min > race_end:
        raise RequestError(
            (
                f"deploy_min {scenario.deploy_min:g} is past the race "
                f"(0 to {race_end:g} minutes)."
            ),
            status=422,
        )
    result = replan_with_safety_car(original, scenario)
    return SafetyCarResponse(
        series="endurance",
        summary=" ".join(result.notes),
        confidence=result.confidence,
        time_delta_min=result.time_delta_min,
        notes=list(result.notes),
        original=_endurance_plan(result.original, body.detail, options),
        replanned=_endurance_plan(result.replanned, body.detail, options),
        disclaimer=DISCLAIMER,
    )


def prepare_event(
    season: int,
    round_: int,
    body: PrepareRequest,
    source: object | None,
) -> PrepareResponse:
    entry = None
    if not body.offline:
        if source is None:
            raise RequestError("No historical source is configured.")
        try:
            entry = source.fetch_entry_list(season, round_)  # type: ignore[attr-defined]
        except HistoricalSourceError:
            raise
    try:
        setup = load_setup(season, round_, entry=entry, overrides=body.overrides)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    gaps = [message for _code, message in readiness_gaps(setup)]
    return PrepareResponse(
        season=setup.season,
        round=setup.round,
        event_name=setup.event_name,
        ready_to_plan=not gaps,
        missing=gaps,
        drivers=[_driver_card(driver) for driver in setup.drivers],
        teams=[_team_card(team) for team in setup.teams],
        image_policy=IMAGE_POLICY,
        assumptions=list(setup.assumptions),
        provenance=dict(setup.provenance),
        setup=setup_to_dict(setup),
    )


def _f1_setup(
    season: int | None,
    round_: int | None,
    document: dict | None,
    overrides: dict,
) -> F1Setup:
    try:
        if document is not None:
            return apply_overrides(setup_from_dict(document), overrides)
        if season is None or round_ is None:
            raise RequestError("Provide season and round, or a setup document.")
        return load_setup(season, round_, overrides=overrides or None)
    except RequestError:
        raise
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def _endurance_config(race: dict | None) -> RaceConfig:
    if race is None:
        raise RequestError("An endurance request needs a race object.")
    try:
        return RaceConfig.from_dict(race)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def _options(body: EnduranceOptionsIn) -> PlanOptions:
    return PlanOptions(
        name=body.name,
        reserve_laps=body.reserve_laps,
        fuel_save_pct=body.fuel_save_pct,
        tyre_change_every_stops=body.tyre_change_every_stops,
        target_stint_fraction=body.target_stint_fraction,
        start_driver_id=body.start_driver_id,
    )


def _f1_plan(plan: F1Plan, detail: str) -> PlanResponse:
    setup = plan.setup
    return PlanResponse(
        series="f1",
        strategy_name=plan.strategy_name,
        feasible=plan.feasible,
        summary=plan.summary,
        why=plan.why,
        race_time_sec=plan.race_time_sec,
        predicted_laps=sum(plan.stint_laps) if plan.stints else None,
        pit_stops=plan.pit_stops,
        stop_laps=list(plan.stop_laps),
        stints=[
            StintOut(
                stint_number=stint.stint_number,
                laps=stint.laps,
                compound=stint.compound_id,
                compound_label=stint.label,
                start_lap=stint.start_lap,
                end_lap=stint.end_lap,
                stop_lap=stint.stop_lap,
                pit_after_sec=stint.pit_after_sec,
            )
            for stint in plan.stints
        ],
        rules=[
            RuleOut(rule_id=rule.rule_id, passed=rule.passed, detail=rule.detail)
            for rule in plan.rules
        ],
        assumptions=list(plan.assumptions),
        infeasibilities=[
            IssueOut(
                code=issue.code, message=issue.message, suggestion=issue.suggestion
            )
            for issue in plan.infeasibilities
        ],
        evidence_level=plan.evidence_level,
        disclaimer=plan.disclaimer,
        uncertainty=plan.uncertainty,
        drivers=[_driver_card(driver) for driver in setup.drivers],
        teams=[_team_card(team) for team in setup.teams],
        image_policy=IMAGE_POLICY,
        provenance=dict(setup.provenance) if detail == "full" else None,
        candidates_checked=plan.candidates_checked if detail == "full" else None,
        ranking_reason=plan.ranking_reason or None,
        rank=plan.rank or None,
        preferred=plan.preferred,
        fuel_used_kg=plan.fuel_used_kg,
    )


def _endurance_plan(
    plan: PlanResult,
    detail: str,
    options: PlanOptions,
    *,
    simulation: SimulationOut | None = None,
    rank: int | None = None,
    preferred: bool | None = None,
    ranking_reason: str | None = None,
    strategy_name: str | None = None,
) -> PlanResponse:
    if plan.is_feasible:
        summary = (
            f"{plan.total_pit_stops} pit stops and {plan.predicted_laps} laps. "
            f"Fuel used is {plan.total_fuel_used_liters:.1f} L. "
            "Compare scenarios for the P10–P90 lap range. "
            "This single plan is the central estimate."
        )
        why = plan.assumptions[0] if plan.assumptions else "Built from the race file."
    else:
        message = (
            plan.infeasibilities[0].message
            if plan.infeasibilities
            else "No legal plan."
        )
        summary = f"This setup cannot make a legal plan. {message}"
        why = message
    if simulation is None:
        uncertainty = f"{UNCERTAINTY} Compare scenarios for the P10–P90 lap range."
    else:
        uncertainty = f"P10 {simulation.laps_p10} to P90 {simulation.laps_p90} laps."
    return PlanResponse(
        series="endurance",
        strategy_name=strategy_name or plan.strategy_name or options.name,
        feasible=plan.is_feasible,
        summary=summary,
        why=why,
        predicted_laps=plan.predicted_laps,
        pit_stops=plan.total_pit_stops,
        stints=[
            StintOut(
                stint_number=stint.stint_number,
                laps=stint.laps,
                driver=stint.driver.name,
                start_min=stint.start_min,
                duration_min=stint.duration_min,
                fuel_added_liters=stint.fuel_added_liters,
                limiting_factor=stint.limiting_factor,
                pit_after_sec=stint.pit_time_after_sec,
            )
            for stint in plan.stints
        ],
        assumptions=list(plan.assumptions),
        infeasibilities=[
            IssueOut(
                code=issue.code, message=issue.message, suggestion=issue.suggestion
            )
            for issue in plan.infeasibilities
        ],
        evidence_level="C",
        disclaimer=DISCLAIMER,
        uncertainty=uncertainty,
        drivers=[
            DriverCard(
                code=driver.id,
                full_name=driver.name,
                team_name=driver.category.value,
                pace_delta_sec=driver.pace_delta_sec,
            )
            for driver in plan.config.drivers
        ],
        image_policy=IMAGE_POLICY,
        provenance=None
        if detail == "plain"
        else {"data_source": plan.config.data_source},
        ranking_reason=ranking_reason,
        rank=rank,
        preferred=preferred,
        total_fuel_used_liters=plan.total_fuel_used_liters,
        simulation=simulation,
    )


def _driver_card(driver: object) -> DriverCard:
    colour = getattr(driver, "team_colour", None)
    return DriverCard(
        code=driver.code,  # type: ignore[attr-defined]
        driver_number=driver.driver_number,  # type: ignore[attr-defined]
        full_name=driver.full_name,  # type: ignore[attr-defined]
        team_name=driver.team_name,  # type: ignore[attr-defined]
        team_colour=colour,
        team_colour_css=colour_css(colour),
        headshot_url=driver.headshot_url,  # type: ignore[attr-defined]
        country_code=driver.country_code,  # type: ignore[attr-defined]
        pace_delta_sec=driver.pace_delta_sec,  # type: ignore[attr-defined]
        car_id=driver.car_id,  # type: ignore[attr-defined]
    )


PRESET_NOTE = (
    "Bundled synthetic preset. Not a World Endurance Championship entry list "
    "and not timing from Al Kamel."
)
TIMING_REFUSAL = (
    "Paste the lap rows you have the right to use. "
    "Pitwall does not fetch a pasted URL, "
    "and it does not redistribute timing data."
)
CLASS_NOTE = (
    "Classes do not interact. There is no traffic, passing, or shared pit lane "
    "between them. Each class is its own plan from the numbers you supplied. "
    "Classes are not combined into one race."
)
DECLARED_WEATHER = (
    "This wet or dry setting is declared by you. It is not a forecast. "
    "Open-Meteo is not called."
)
SHEET_NOTE = (
    "Created a new file. race.json was not written and nothing was overwritten."
)
COMMERCIAL_NOTE = (
    "Review these terms before any public or commercial release. "
    "This build is not a commercial licence for OpenF1 or Jolpica data."
)
SHEET_DIR = Path.cwd() / ".cache" / "pitwall-sheets"


def endurance_presets() -> dict[str, object]:
    return {"presets": list_presets(), "note": PRESET_NOTE}


def endurance_preset(name: str) -> dict[str, object]:
    known = list_presets()
    if name not in known:
        raise RequestError(
            f"Unknown preset {name}. Known presets: {', '.join(known)}.",
            status=404,
        )
    config = load_preset(name)
    return {
        "name": name,
        "synthetic": True,
        "evidence_level": "C",
        "note": PRESET_NOTE,
        "race": config.to_dict(),
    }


def endurance_classes(body: ClassesRequest) -> ClassesResponse:
    rows: list[ClassPlanOut] = []
    for item in body.classes:
        config = _endurance_config(item.race)
        plan = compute_plan(config)
        rows.append(
            ClassPlanOut(
                name=item.name,
                plan=_endurance_plan(plan, "full", PlanOptions()),
            )
        )
    return ClassesResponse(classes=rows, note=CLASS_NOTE)


def endurance_telemetry(body: TelemetryRequest) -> dict[str, object]:
    if _remote_timing(body.csv):
        raise RequestError(TIMING_REFUSAL)
    try:
        calibrated = calibrate_telemetry(
            body.csv, source_name="pasted.csv", is_synthetic=body.synthetic
        )
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    report = calibrated.to_report()
    report["config_patch"] = calibrated.config_patch()
    report["usable_for_strategy"] = calibrated.usable_for_strategy
    return report


def declared_weather(body: DeclaredWeatherRequest) -> DeclaredWeatherResponse:
    overrides: dict[str, object] = {"dry_race": body.declared == "dry"}
    note = DECLARED_WEATHER
    if body.declared == "wet":
        compounds: dict[str, object] = {
            name: {"max_laps": None} for name in ("SOFT", "MEDIUM", "HARD")
        }
        life = body.wet_life_laps
        if life is not None:
            compounds["INTERMEDIATE"] = {"max_laps": life}
            compounds["WET"] = {"max_laps": life}
            note = (
                f"{DECLARED_WEATHER} Intermediate and Wet life are the {life} laps you typed. "
                "Their pace and degradation stay at the file default. Slicks are not used."
            )
        else:
            note = (
                f"{DECLARED_WEATHER} A declared wet race uses Intermediate and Wet, not slicks. "
                "This file gives them no stint life, so there is no wet plan."
            )
        overrides["compounds"] = compounds
    setup = _f1_setup(body.season, body.round, None, overrides)
    return DeclaredWeatherResponse(
        declared=body.declared,
        forecast=False,
        open_meteo="not called",
        note=note,
        plan=_f1_plan(best_f1_plan(setup), "full"),
    )


def licence_terms() -> dict[str, str]:
    return {
        "openf1": OPENF1_TERMS,
        "jolpica": JOLPICA_TERMS,
        "wec": WEC_NOTICE,
        "commercial": COMMERCIAL_NOTE,
    }


def save_sheet(body: SheetRequest, root: Path | None = None) -> SheetResponse:
    folder = (root or SHEET_DIR).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    filename = _sheet_filename(body.name)
    target = (folder / filename).resolve()
    if target.parent != folder:
        raise RequestError("Choose a sheet name that stays in the sheet folder.")
    payload = {"note": SHEET_NOTE, "document": body.document}
    text = json.dumps(payload, indent=2, sort_keys=True)
    if len(text.encode("utf-8")) > 256 * 1024:
        raise RequestError("That sheet is larger than 256 KiB.")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RequestError(
            f"{filename} already exists. Choose a new name. Nothing was overwritten.",
            status=409,
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n")
    return SheetResponse(
        name=filename, created=True, note=SHEET_NOTE, document=body.document
    )


def _sheet_filename(value: str) -> str:
    stem = Path(value).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(stem).stem).strip(".-_")
    if not cleaned or cleaned.lower() in {"race", "race.json"}:
        raise RequestError("Choose a sheet name that is not race.json.")
    return cleaned[:80] + ".json"


def _remote_timing(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        return lowered.startswith("http://") or lowered.startswith("https://")
    return False


def f1_undercut(body: UndercutRequest) -> dict[str, object]:
    try:
        return undercut(
            gap_behind_sec=body.gap_behind_sec,
            laps_ahead=body.laps_ahead,
            tyre_gain_sec_per_lap=body.tyre_gain_sec_per_lap,
            our_pit_loss_sec=body.our_pit_loss_sec,
            their_pit_loss_sec=body.their_pit_loss_sec,
            out_lap_warmup_sec=body.out_lap_warmup_sec,
            in_lap_delta_sec=body.in_lap_delta_sec,
            traffic_avoided_sec=body.traffic_avoided_sec,
        )
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def f1_odds(body: OddsRequest) -> dict[str, object]:
    try:
        setup = load_setup(body.season, body.round)
    except ValueError as exc:
        raise RequestError(str(exc), status=404) from exc
    plan = best_f1_plan(setup)
    if not plan.feasible:
        raise RequestError("No feasible plan to sample.")
    try:
        sampled = race_time_odds(
            setup,
            [(stint.compound_id, stint.laps) for stint in plan.stints],
            iterations=body.iterations,
        )
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    sampled["compounds"] = [stint.compound_id for stint in plan.stints]
    sampled["stint_laps"] = [stint.laps for stint in plan.stints]
    return sampled


def _team_card(team: object) -> TeamCard:
    colour = getattr(team, "team_colour", None)
    return TeamCard(
        team_name=team.team_name,  # type: ignore[attr-defined]
        team_colour=colour,
        team_colour_css=colour_css(colour),
        livery_image_url=team.livery_image_url,  # type: ignore[attr-defined]
    )
