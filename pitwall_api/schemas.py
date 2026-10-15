"""Typed HTTP bodies. Image fields are URLs only."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EnduranceOptionsIn(BaseModel):
    name: str = "Balanced"
    reserve_laps: int | None = None
    fuel_save_pct: float = 0.0
    tyre_change_every_stops: int = 1
    target_stint_fraction: float = 1.0
    start_driver_id: str | None = None


class StintIn(BaseModel):
    compound: str = Field(min_length=1, max_length=40)
    laps: int = Field(ge=1, le=500)


class ScenarioIn(BaseModel):
    name: str
    stints: list[StintIn] | None = None


class PlanRequest(BaseModel):
    series: Literal["f1", "endurance"]
    season: int | None = Field(default=None, ge=1950, le=2100)
    round: int | None = Field(default=None, ge=1, le=30)
    setup: dict | None = None
    overrides: dict = Field(default_factory=dict)
    race: dict | None = None
    options: EnduranceOptionsIn = Field(default_factory=EnduranceOptionsIn)
    strategy: list[StintIn] | None = Field(default=None, max_length=8)
    detail: Literal["plain", "full"] = "full"


class CompareRequest(BaseModel):
    series: Literal["f1", "endurance"]
    season: int | None = Field(default=None, ge=1950, le=2100)
    round: int | None = Field(default=None, ge=1, le=30)
    setup: dict | None = None
    overrides: dict = Field(default_factory=dict)
    race: dict | None = None
    scenarios: list[ScenarioIn] = Field(default_factory=list, max_length=8)
    detail: Literal["plain", "full"] = "full"


class SafetyCarRequestIn(BaseModel):
    series: Literal["f1", "endurance"]
    season: int | None = Field(default=None, ge=1950, le=2100)
    round: int | None = Field(default=None, ge=1, le=30)
    setup: dict | None = None
    overrides: dict = Field(default_factory=dict)
    race: dict | None = None
    options: EnduranceOptionsIn = Field(default_factory=EnduranceOptionsIn)
    strategy: list[StintIn] | None = Field(default=None, max_length=8)
    safety_car: dict
    detail: Literal["plain", "full"] = "full"


class PrepareRequest(BaseModel):
    offline: bool = False
    overrides: dict = Field(default_factory=dict)


class ReplayRequest(BaseModel):
    overrides: dict = Field(default_factory=dict)
    anchor_pace: bool = False


class UndercutRequest(BaseModel):
    gap_behind_sec: float = Field(ge=0)
    laps_ahead: int = Field(ge=1)
    tyre_gain_sec_per_lap: float
    our_pit_loss_sec: float = Field(ge=0)
    their_pit_loss_sec: float = Field(ge=0)
    out_lap_warmup_sec: float = Field(default=0, ge=0)
    in_lap_delta_sec: float = Field(default=0, ge=0)
    traffic_avoided_sec: float = Field(default=0, ge=0)


class OddsRequest(BaseModel):
    season: int
    round: int
    iterations: int = Field(default=64, ge=1, le=400)


class TelemetryRequest(BaseModel):
    csv: str = Field(min_length=1, max_length=200_000)
    synthetic: bool = False


class ClassIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    race: dict


class ClassesRequest(BaseModel):
    classes: list[ClassIn] = Field(min_length=1, max_length=4)


class DeclaredWeatherRequest(BaseModel):
    season: int
    round: int
    declared: Literal["dry", "wet"]
    wet_life_laps: int | None = Field(default=None, ge=1, le=80)


class SheetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    document: dict


class IssueOut(BaseModel):
    code: str
    message: str
    suggestion: str = ""


class RuleOut(BaseModel):
    rule_id: str
    passed: bool
    detail: str


class StintOut(BaseModel):
    stint_number: int
    laps: int
    compound: str | None = None
    compound_label: str | None = None
    start_lap: int | None = None
    end_lap: int | None = None
    stop_lap: int | None = None
    driver: str | None = None
    start_min: float | None = None
    duration_min: float | None = None
    fuel_added_liters: float | None = None
    limiting_factor: str | None = None
    pit_after_sec: float | None = None


class SimulationOut(BaseModel):
    laps_p10: float
    laps_median: float
    laps_p90: float
    extra_stop_probability: float
    source: str
    confidence: str


class DriverCard(BaseModel):
    code: str
    driver_number: int | None = None
    full_name: str = ""
    team_name: str = ""
    team_colour: str | None = None
    team_colour_css: str | None = None
    headshot_url: str | None = None
    country_code: str | None = None
    pace_delta_sec: float = 0.0
    car_id: str | None = None


class TeamCard(BaseModel):
    team_name: str
    team_colour: str | None = None
    team_colour_css: str | None = None
    livery_image_url: str | None = None


class PlanResponse(BaseModel):
    series: str
    strategy_name: str
    feasible: bool
    summary: str
    why: str
    race_time_sec: float | None = None
    predicted_laps: int | None = None
    pit_stops: int
    stop_laps: list[int] = Field(default_factory=list)
    stints: list[StintOut]
    rules: list[RuleOut] = Field(default_factory=list)
    assumptions: list[str]
    infeasibilities: list[IssueOut]
    evidence_level: str
    disclaimer: str
    uncertainty: str
    drivers: list[DriverCard] = Field(default_factory=list)
    teams: list[TeamCard] = Field(default_factory=list)
    image_policy: str
    provenance: dict[str, str] | None = None
    candidates_checked: int | None = None
    ranking_reason: str | None = None
    rank: int | None = None
    preferred: bool | None = None
    fuel_used_kg: float | None = None
    total_fuel_used_liters: float | None = None
    simulation: SimulationOut | None = None


class CompareResponse(BaseModel):
    series: str
    scenarios: list[PlanResponse]
    image_policy: str
    disclaimer: str


class ClassPlanOut(BaseModel):
    name: str
    plan: PlanResponse


class ClassesResponse(BaseModel):
    classes: list[ClassPlanOut]
    note: str


class DeclaredWeatherResponse(BaseModel):
    declared: Literal["dry", "wet"]
    forecast: bool
    open_meteo: str
    note: str
    plan: PlanResponse


class SheetResponse(BaseModel):
    name: str
    created: bool
    note: str
    document: dict


class SafetyCarResponse(BaseModel):
    series: str
    summary: str
    confidence: str
    time_saved_sec: float | None = None
    time_delta_min: float | None = None
    stop_laps: list[int] = Field(default_factory=list)
    stops_moved: bool | None = None
    notes: list[str]
    original: PlanResponse
    replanned: PlanResponse
    disclaimer: str


class PrepareResponse(BaseModel):
    season: int
    round: int
    event_name: str
    ready_to_plan: bool
    missing: list[str]
    drivers: list[DriverCard]
    teams: list[TeamCard]
    image_policy: str
    assumptions: list[str]
    provenance: dict[str, str]
    setup: dict


class BacktestResponse(BaseModel):
    event_name: str
    season: int
    round: int
    driver_number: int
    driver_code: str
    full_name: str
    team_name: str
    team_colour: str | None
    team_colour_css: str | None
    headshot_url: str | None
    livery_image_url: str | None
    actual_compounds: list[str]
    actual_stint_laps: list[int]
    actual_stop_laps: list[int]
    actual_pit_durations_sec: list[float]
    actual_race_time_sec: float | None
    predicted_compounds: list[str]
    predicted_stint_laps: list[int]
    predicted_stop_laps: list[int]
    predicted_race_time_sec: float | None
    replay_race_time_sec: float | None
    race_time_delta_sec: float | None
    replay_time_delta_sec: float | None
    stop_count_delta: int
    same_stop_count: bool
    stint_length_deltas: list[int] | None
    pace_anchor_sec: float | None
    evidence_level: str
    notes: list[str]
    image_policy: str
