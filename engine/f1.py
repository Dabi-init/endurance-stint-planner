"""F1 strategy rules beside the endurance planner.

Endurance races stay in ``engine.planner`` (a clock, refuelling, driver
rotation). An F1 race here is a fixed lap count: no refuelling, a configured
pit-lane loss, and a minimum number of dry compounds when every stint is a
slick. A wet-weather tyre is legal in a dry race and lifts that requirement.
Tyre life, pace, degradation, fuel mass, and pit loss are inputs.
Nothing in this module is a measured circuit fact.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from engine.models import Infeasibility

DISCLAIMER = (
    "Pre-race estimate from the configured rules and assumptions. "
    "Not live timing, not an official regulation text, and not a validated prediction."
)
UNCERTAINTY = (
    "Not estimated. This phase returns one deterministic time, not a P10–P90 range."
)
MAX_STOP_SEARCH = 4


@dataclass(frozen=True)
class CompoundSpec:
    compound_id: str
    label: str
    dry: bool
    colour: str = ""
    max_laps: int | None = None
    pace_delta_sec: float = 0.0
    deg_sec_per_lap: float = 0.0


@dataclass(frozen=True)
class UpgradeSpec:
    upgrade_id: str
    pace_delta_sec: float
    note: str = ""


@dataclass(frozen=True)
class CarSpec:
    car_id: str
    team_name: str = ""
    team_colour: str | None = None
    livery_image_url: str | None = None
    pace_delta_sec: float = 0.0
    fuel_capacity_kg: float | None = None
    fuel_consumption_kg_per_lap: float | None = None
    starting_fuel_kg: float | None = None
    upgrades: tuple[UpgradeSpec, ...] = ()


@dataclass(frozen=True)
class DriverSpec:
    code: str
    driver_number: int | None = None
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    team_name: str = ""
    team_colour: str | None = None
    headshot_url: str | None = None
    country_code: str | None = None
    pace_delta_sec: float = 0.0
    car_id: str | None = None


@dataclass(frozen=True)
class TeamSpec:
    team_name: str
    team_colour: str | None = None
    livery_image_url: str | None = None


@dataclass
class F1Setup:
    """One resolved event: season rules, event file, entry list, user overrides."""

    season: int
    round: int
    event_name: str
    circuit_id: str = ""
    race_laps: int | None = None
    dry_race: bool = True
    time_limit_sec: float | None = None
    pit_lane_loss_sec: float | None = None
    base_lap_time_sec: float | None = None
    refuelling_allowed: bool = False
    dry_min_compounds: int = 2
    wet_min_compounds: int = 1
    max_stops: int = 3
    compounds: list[CompoundSpec] = field(default_factory=list)
    cars: list[CarSpec] = field(default_factory=list)
    drivers: list[DriverSpec] = field(default_factory=list)
    teams: list[TeamSpec] = field(default_factory=list)
    focus_driver: str | None = None
    evidence_level: str = "C"
    data_source: str = ""
    provenance: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    schema_version: int = 1

    def compound(self, compound_id: str) -> CompoundSpec | None:
        key = compound_id.upper()
        for compound in self.compounds:
            if compound.compound_id == key:
                return compound
        return None


@dataclass(frozen=True)
class StintRequest:
    compound: str
    laps: int


@dataclass(frozen=True)
class F1Stint:
    stint_number: int
    compound_id: str
    label: str
    laps: int
    start_lap: int
    end_lap: int
    stop_lap: int | None
    stint_time_sec: float
    pit_after_sec: float


@dataclass(frozen=True)
class F1RuleCheck:
    rule_id: str
    passed: bool
    detail: str


@dataclass
class F1Plan:
    setup: F1Setup
    strategy_name: str
    stints: list[F1Stint] = field(default_factory=list)
    race_time_sec: float | None = None
    pit_stops: int = 0
    stop_laps: list[int] = field(default_factory=list)
    fuel_used_kg: float | None = None
    feasible: bool = False
    infeasibilities: list[Infeasibility] = field(default_factory=list)
    rules: list[F1RuleCheck] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    summary: str = ""
    why: str = ""
    ranking_reason: str = ""
    rank: int = 0
    preferred: bool = False
    candidates_checked: int = 0
    evidence_level: str = "C"
    disclaimer: str = DISCLAIMER
    uncertainty: str = UNCERTAINTY
    pace_base_sec: float | None = None

    @property
    def compounds_used(self) -> list[str]:
        return [stint.compound_id for stint in self.stints]

    @property
    def stint_laps(self) -> list[int]:
        return [stint.laps for stint in self.stints]


@dataclass(frozen=True)
class ScenarioRequest:
    name: str
    stints: tuple[StintRequest, ...] | None = None


@dataclass
class SafetyCarRequest:
    start_lap: int
    end_lap: int
    pit_loss_sec: float
    pull_pit_into_sc: bool = True
    field_lap_delta_sec: float = 0.0
    rival_stops: int = 0


@dataclass
class SafetyCarResult:
    original: F1Plan
    replanned: F1Plan
    original_race_time_sec: float | None
    replanned_race_time_sec: float | None
    time_saved_sec: float
    stop_laps: list[int]
    stops_moved: bool
    summary: str
    confidence: str
    assumptions: list[str] = field(default_factory=list)


def lap_time_ms(
    base_sec: float, delta_sec: float, deg_sec_per_lap: float, index: int
) -> int:
    """Lap time in milliseconds, rounded to the nearest millisecond.

    ``index`` is 0 on the first lap of the stint. Degradation is linear.
    """
    seconds = base_sec + delta_sec + deg_sec_per_lap * index
    return round(seconds * 1000)


def format_race_time(seconds: float) -> str:
    total_ms = round(max(seconds, 0.0) * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes}:{secs:02d}.{millis:03d}"


def best_lap_split(
    total: int,
    limits: list[int],
    stint_cost_ms: list[Callable[[int], int]],
) -> list[int] | None:
    """Choose stint lengths that minimise driving time.

    Each stint is at least one lap and at most its life. Equal times keep the
    lexicographically smaller length tuple, so the result does not depend on
    search order. ``stint_cost_ms[i]`` is a callable from laps to milliseconds.
    """
    count = len(limits)
    if count == 0 or total < count or any(limit < 1 for limit in limits):
        return None
    if sum(limits) < total:
        return None
    best: list[dict[int, tuple[int, tuple[int, ...]]]] = [
        dict() for _ in range(count + 1)
    ]
    best[0][0] = (0, ())
    for index, limit in enumerate(limits):
        cost = stint_cost_ms[index]
        for used, (spent, prefix) in best[index].items():
            remaining_stints = count - index - 1
            max_laps = min(limit, total - used - remaining_stints)
            for laps in range(1, max_laps + 1):
                nxt = used + laps
                candidate = (spent + cost(laps), (*prefix, laps))
                current = best[index + 1].get(nxt)
                if current is None or candidate < current:
                    best[index + 1][nxt] = candidate
    found = best[count].get(total)
    if found is None:
        return None
    return list(found[1])


def readiness_gaps(setup: F1Setup) -> list[tuple[str, str]]:
    """Plain reasons a plan cannot start. The strings are the user-facing copy."""
    gaps: list[tuple[str, str]] = []
    if setup.race_laps is None or setup.race_laps < 1:
        gaps.append(("missing_race_laps", "Add the race distance in laps."))
    if setup.pit_lane_loss_sec is None or setup.pit_lane_loss_sec < 0:
        gaps.append(("missing_pit_loss", "Add the pit-lane time loss in seconds."))
    if setup.base_lap_time_sec is None or setup.base_lap_time_sec <= 0:
        gaps.append(("missing_base_lap", "Add a base lap time in seconds."))
    if not any(
        compound.max_laps and compound.max_laps > 0 for compound in setup.compounds
    ):
        gaps.append(
            (
                "missing_compound_life",
                "Add how many laps each dry tyre can do.",
            )
        )
    if len(setup.drivers) > 1 and not setup.focus_driver:
        gaps.append(("missing_focus", "Choose the driver you are planning for."))
    return gaps


def _issue(code: str, message: str, suggestion: str = "") -> Infeasibility:
    return Infeasibility(code, message, suggestion)


def _empty_plan(
    setup: F1Setup,
    name: str,
    issues: list[Infeasibility],
    rules: list[F1RuleCheck] | None = None,
) -> F1Plan:
    plan = F1Plan(
        setup=setup,
        strategy_name=name,
        infeasibilities=issues,
        rules=rules or [],
        assumptions=list(setup.assumptions),
        evidence_level=setup.evidence_level,
        feasible=False,
    )
    plan.summary = _summary(plan)
    plan.why = issues[0].message if issues else ""
    return plan


def _select_driver(setup: F1Setup) -> tuple[DriverSpec | None, str | None]:
    if setup.focus_driver:
        code = setup.focus_driver.upper()
        found = [driver for driver in setup.drivers if driver.code == code]
        if not found:
            return None, "unknown_driver"
        return found[0], None
    if len(setup.drivers) == 1:
        return setup.drivers[0], "only"
    if len(setup.drivers) > 1:
        return None, "missing_focus"
    return None, None


def _select_car(
    setup: F1Setup, driver: DriverSpec | None
) -> tuple[CarSpec | None, str | None]:
    if driver and driver.car_id:
        matches = [car for car in setup.cars if car.car_id == driver.car_id]
        if not matches:
            return None, "missing_car"
        return matches[0], None
    if driver and driver.team_name:
        matches = [car for car in setup.cars if car.team_name == driver.team_name]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "ambiguous_car"
    if len(setup.cars) == 1:
        return setup.cars[0], None
    if not setup.cars:
        return None, "missing_car"
    return None, "ambiguous_car"


def _pace_base(setup: F1Setup, car: CarSpec | None, driver: DriverSpec | None) -> float:
    base = float(setup.base_lap_time_sec or 0.0)
    if car is not None:
        base += car.pace_delta_sec
        base += sum(upgrade.pace_delta_sec for upgrade in car.upgrades)
    if driver is not None:
        base += driver.pace_delta_sec
    return base


def _join(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def _summary(plan: F1Plan) -> str:
    if not plan.feasible:
        lead = (
            plan.infeasibilities[0].message
            if plan.infeasibilities
            else "No legal plan."
        )
        return f"This setup cannot make a legal plan. {lead}"
    if plan.pit_stops == 0:
        stop_text = "No pit stop."
    elif plan.pit_stops == 1:
        stop_text = "One pit stop."
    else:
        stop_text = f"{plan.pit_stops} pit stops."
    parts = [f"{stint.laps} laps on the {stint.label} tyre" for stint in plan.stints]
    clock = format_race_time(plan.race_time_sec or 0.0)
    return (
        f"{stop_text} {_join(parts)}. "
        f"Estimated race time {clock}. "
        "The car does not refuel during the race."
    )


def _why(
    setup: F1Setup, stints: list[F1Stint], feasible: bool, issues: list[Infeasibility]
) -> str:
    if not feasible:
        return issues[0].message if issues else ""
    labels: list[str] = []
    non_slick = False
    for stint in stints:
        if stint.label not in labels:
            labels.append(stint.label)
        compound = setup.compound(stint.compound_id)
        if compound is not None and not compound.dry:
            non_slick = True
    if non_slick:
        return (
            "A wet-weather tyre is in this plan, so the two-compound slick rule does not apply. "
            f"This plan uses {_join(labels)}. "
            "Every stint stays within the tyre life in the file."
        )
    required = setup.dry_min_compounds
    noun = "tyre type" if required == 1 else "tyre types"
    return (
        f"A dry race in this rule file needs at least {required} different {noun}. "
        f"This plan uses {_join(labels)}. "
        "Every stint stays within the tyre life in the file."
    )


def _stint_ms(laps: int, base: float, compound: CompoundSpec) -> int:
    return sum(
        lap_time_ms(base, compound.pace_delta_sec, compound.deg_sec_per_lap, index)
        for index in range(laps)
    )


def _stint_cost(base: float, compound: CompoundSpec) -> Callable[[int], int]:
    def cost(laps: int) -> int:
        return _stint_ms(laps, base, compound)

    return cost


def score_stints(
    setup: F1Setup,
    requests: list[StintRequest] | tuple[StintRequest, ...],
    *,
    name: str = "Custom",
    pit_losses_sec: list[float] | None = None,
    candidates_checked: int = 1,
) -> F1Plan:
    """Time one tyre sequence and check it against the file's rules."""
    gaps = readiness_gaps(setup)
    if gaps and any(code != "missing_focus" for code, _message in gaps):
        issues = [
            _issue(
                code, message, "Set the missing value in the event file or an override."
            )
            for code, message in gaps
            if code != "missing_focus"
        ]
        return _empty_plan(setup, name, issues)

    driver, driver_problem = _select_driver(setup)
    if driver_problem == "unknown_driver":
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "unknown_driver",
                    f"No driver {setup.focus_driver} is in this entry list.",
                    "Pick a driver code from the entry list.",
                )
            ],
        )
    if driver_problem == "missing_focus":
        return _empty_plan(
            setup,
            name,
            [_issue("missing_focus", "Choose the driver you are planning for.")],
        )

    car, car_problem = _select_car(setup, driver)
    if car_problem == "missing_car":
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "missing_car",
                    "Add a car spec, including the fuel load, before planning.",
                    "Put fuel capacity and consumption in the event file.",
                )
            ],
        )
    if car_problem == "ambiguous_car":
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "ambiguous_car",
                    "More than one car matches this driver. Set car_id.",
                    "Point the driver at one car spec.",
                )
            ],
        )

    rows = list(requests)
    if not rows:
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "empty_strategy",
                    "Add at least one stint.",
                    "Name a tyre and a lap count.",
                )
            ],
        )

    unknown = [
        request.compound for request in rows if setup.compound(request.compound) is None
    ]
    if unknown:
        names = ", ".join(unknown)
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "unknown_compound",
                    f"Unknown tyre {names}.",
                    "Use a tyre id from the season file.",
                )
            ],
        )
    if any(request.laps < 1 for request in rows):
        return _empty_plan(
            setup,
            name,
            [_issue("invalid_stint", "Every stint needs at least one lap.")],
        )

    race_laps = int(setup.race_laps or 0)
    total = sum(request.laps for request in rows)
    if total != race_laps:
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "lap_sum",
                    f"The stints add up to {total} laps, not the {race_laps}-lap race.",
                    "Make the stint laps add up to the race distance.",
                )
            ],
        )

    assert car is not None
    base = _pace_base(setup, car, driver)
    built: list[F1Stint] = []
    cursor = 1
    driving_ms = 0
    stops = len(rows) - 1
    if pit_losses_sec is None:
        losses = [float(setup.pit_lane_loss_sec or 0.0)] * stops
    else:
        losses = list(pit_losses_sec)
    if len(losses) != stops:
        return _empty_plan(
            setup,
            name,
            [_issue("pit_losses", "Each stop needs one pit-loss value.")],
        )

    for index, request in enumerate(rows):
        compound = setup.compound(request.compound)
        assert compound is not None
        stint_ms = _stint_ms(request.laps, base, compound)
        driving_ms += stint_ms
        end_lap = cursor + request.laps - 1
        pit_after = losses[index] if index < stops else 0.0
        built.append(
            F1Stint(
                stint_number=index + 1,
                compound_id=compound.compound_id,
                label=compound.label,
                laps=request.laps,
                start_lap=cursor,
                end_lap=end_lap,
                stop_lap=end_lap if index < stops else None,
                stint_time_sec=stint_ms / 1000,
                pit_after_sec=pit_after,
            )
        )
        cursor = end_lap + 1

    pit_ms = sum(round(loss * 1000) for loss in losses)
    race_time = (driving_ms + pit_ms) / 1000
    fuel_used = None
    if car.fuel_consumption_kg_per_lap is not None:
        fuel_used = round(car.fuel_consumption_kg_per_lap * race_laps, 3)

    rules, issues = _rule_checks(setup, car, built, race_time, fuel_used)
    plan = F1Plan(
        setup=setup,
        strategy_name=name,
        stints=built,
        race_time_sec=race_time,
        pit_stops=stops,
        stop_laps=[stint.stop_lap for stint in built if stint.stop_lap is not None],
        fuel_used_kg=fuel_used,
        feasible=not issues,
        infeasibilities=issues,
        rules=rules,
        evidence_level=setup.evidence_level,
        candidates_checked=candidates_checked,
        pace_base_sec=base,
    )
    plan.assumptions = _assumptions(setup, car, driver, driver_problem == "only", base)
    plan.summary = _summary(plan)
    plan.why = _why(setup, built, plan.feasible, issues)
    return plan


def _rule_checks(
    setup: F1Setup,
    car: CarSpec,
    stints: list[F1Stint],
    race_time: float,
    fuel_used: float | None,
) -> tuple[list[F1RuleCheck], list[Infeasibility]]:
    rules: list[F1RuleCheck] = []
    issues: list[Infeasibility] = []

    if setup.refuelling_allowed:
        detail = (
            "This file allows refuelling, and this F1 planner does not add fuel. "
            "Use the endurance planner for a race that refuels."
        )
        rules.append(F1RuleCheck("no_refuelling", False, detail))
        issues.append(
            _issue(
                "refuel_not_modelled",
                detail,
                "Set refuelling_allowed to false, or plan the race as endurance.",
            )
        )
    else:
        rules.append(
            F1RuleCheck(
                "no_refuelling",
                True,
                "Refuelling is off in this file, and the plan does not add fuel.",
            )
        )

    if (
        car.fuel_capacity_kg is None
        or car.fuel_consumption_kg_per_lap is None
        or car.starting_fuel_kg is None
        or fuel_used is None
    ):
        detail = "Add fuel capacity, starting fuel, and consumption in kilograms."
        rules.append(F1RuleCheck("fuel_range", False, detail))
        issues.append(
            _issue("missing_fuel", detail, "Set the car fuel fields in the event file.")
        )
    else:
        start_mg = round(car.starting_fuel_kg * 1000)
        tank_mg = round(car.fuel_capacity_kg * 1000)
        used_mg = round(fuel_used * 1000)
        if start_mg > tank_mg:
            detail = (
                f"Starting fuel {car.starting_fuel_kg:.3f} kg is above the "
                f"{car.fuel_capacity_kg:.3f} kg tank."
            )
            rules.append(F1RuleCheck("fuel_range", False, detail))
            issues.append(_issue("fuel_capacity", detail, "Lower the starting fuel."))
        elif used_mg > start_mg:
            detail = (
                f"The race needs {fuel_used:.3f} kg and the car starts with "
                f"{car.starting_fuel_kg:.3f} kg. No fuel is added at the stops."
            )
            rules.append(F1RuleCheck("fuel_range", False, detail))
            issues.append(
                _issue(
                    "fuel_range",
                    detail,
                    "Raise the starting fuel or lower the consumption assumption.",
                )
            )
        else:
            rules.append(
                F1RuleCheck(
                    "fuel_range",
                    True,
                    (
                        f"Fuel used {fuel_used:.3f} kg of {car.starting_fuel_kg:.3f} kg "
                        "on board. No fuel is added at the stops."
                    ),
                )
            )

    dry_ids = [stint.compound_id for stint in stints]
    compounds = [setup.compound(stint.compound_id) for stint in stints]
    all_slick = bool(compounds) and all(
        compound is not None and compound.dry for compound in compounds
    )
    if not all_slick:
        labels = [
            setup.compound(item).label
            for item in dict.fromkeys(dry_ids)
            if setup.compound(item) is not None
        ]
        rules.append(
            F1RuleCheck(
                "compound_count",
                True,
                (
                    f"Used {_join(labels)}. A wet-weather tyre is in this plan, "
                    "so the two-compound slick rule does not apply."
                ),
            )
        )
    else:
        distinct = list(dict.fromkeys(dry_ids))
        required = setup.dry_min_compounds
        kind = "dry"
        if len(distinct) < required:
            detail = (
                f"Used {_join([setup.compound(item).label for item in distinct if setup.compound(item)])} "
                f"({len(distinct)}). A {kind} race in this file needs at least {required}."
            )
            rules.append(F1RuleCheck("compound_count", False, detail))
            issues.append(
                _issue(
                    "compound_rule",
                    detail,
                    "Add another tyre type, or change the compound rule in your override.",
                )
            )
        else:
            labels = [
                setup.compound(item).label
                for item in distinct
                if setup.compound(item) is not None
            ]
            rules.append(
                F1RuleCheck(
                    "compound_count",
                    True,
                    (
                        f"Used {_join(labels)} ({len(distinct)}). "
                        f"A {kind} race in this file needs at least {required}."
                    ),
                )
            )

    life_bits: list[str] = []
    life_failed = False
    for stint in stints:
        compound = setup.compound(stint.compound_id)
        assert compound is not None
        life = compound.max_laps
        if life is None or stint.laps > life:
            life_failed = True
            shown = "no life" if life is None else f"the {life}-lap life"
            life_bits.append(f"{stint.label} {stint.laps} laps exceeds {shown}")
        else:
            life_bits.append(f"{stint.label} {stint.laps} laps of {life}")
    life_detail = ". ".join(life_bits) + "."
    rules.append(F1RuleCheck("tyre_life", not life_failed, life_detail))
    if life_failed:
        issues.append(
            _issue(
                "tyre_life",
                life_detail,
                "Shorten the stint or raise that tyre's life in the file.",
            )
        )

    if setup.time_limit_sec is not None and race_time > setup.time_limit_sec:
        detail = (
            f"Estimated race time {format_race_time(race_time)} is past "
            f"the {setup.time_limit_sec:.0f} s time limit."
        )
        rules.append(F1RuleCheck("time_limit", False, detail))
        issues.append(
            _issue(
                "time_limit",
                detail,
                "The race would not reach this lap count inside the limit.",
            )
        )
    elif setup.time_limit_sec is not None:
        rules.append(
            F1RuleCheck(
                "time_limit",
                True,
                (
                    f"Estimated race time {format_race_time(race_time)} is inside "
                    f"the {setup.time_limit_sec:.0f} s limit."
                ),
            )
        )
    return rules, issues


def _assumptions(
    setup: F1Setup,
    car: CarSpec,
    driver: DriverSpec | None,
    only_driver: bool,
    base: float,
) -> list[str]:
    notes = list(setup.assumptions)
    notes.append(setup.data_source or "No data-source note on this file.")
    notes.append(
        f"Pit-lane time loss is {setup.pit_lane_loss_sec:.1f} s per stop. "
        "That number comes from the file, not from a measured pit stop."
    )
    notes.append("No refuelling during the race.")
    notes.append(
        f"Pace base used for every lap is {base:.3f} s before tyre delta and wear."
    )
    if only_driver and driver is not None:
        notes.append(f"Planning the only driver in the list ({driver.code}).")
    if car.upgrades:
        bits = ", ".join(
            f"{upgrade.upgrade_id} ({upgrade.pace_delta_sec:+.3f} s)"
            for upgrade in car.upgrades
        )
        notes.append(f"Team upgrades from the file: {bits}.")
    notes.append(
        "Tyre life and pace deltas come from the event file, not from a measured model."
    )
    notes.append(UNCERTAINTY)
    notes.append(f"Evidence level {setup.evidence_level}.")
    return notes


def _available(setup: F1Setup) -> list[CompoundSpec]:
    """Compounds with a stint life, slicks and wet-weather tyres together."""
    return [
        compound
        for compound in setup.compounds
        if compound.max_laps is not None and compound.max_laps >= 1
    ]


def _slick_rule_blocks(combo: tuple[CompoundSpec, ...], minimum: int) -> bool:
    """The two-compound rule applies only when every stint in the sequence is a slick."""
    if not combo or not all(compound.dry for compound in combo):
        return False
    return len({compound.compound_id for compound in combo}) < minimum


def _rank_key(plan: F1Plan) -> tuple[float, int, tuple[str, ...], tuple[int, ...]]:
    time = plan.race_time_sec if plan.race_time_sec is not None else math.inf
    return (time, plan.pit_stops, tuple(plan.compounds_used), tuple(plan.stint_laps))


def best_f1_plan(setup: F1Setup, *, name: str = "Suggested") -> F1Plan:
    """Search legal tyre sequences and return the lowest race time."""
    gaps = readiness_gaps(setup)
    blocking = [
        gap for gap in gaps if gap[0] != "missing_focus" or len(setup.drivers) > 1
    ]
    if any(code != "missing_focus" for code, _message in gaps) or (
        len(setup.drivers) > 1 and not setup.focus_driver
    ):
        issues = [
            _issue(
                code, message, "Set the missing value in the event file or an override."
            )
            for code, message in blocking
        ]
        return _empty_plan(setup, name, issues)
    if setup.max_stops > MAX_STOP_SEARCH:
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "stop_search_too_wide",
                    f"This planner searches at most {MAX_STOP_SEARCH} stops.",
                    "Lower max_stops in the rule file.",
                )
            ],
        )
    if setup.refuelling_allowed:
        detail = (
            "This file allows refuelling, and this F1 planner does not add fuel. "
            "Use the endurance planner for a race that refuels."
        )
        return _empty_plan(
            setup,
            name,
            [
                _issue(
                    "refuel_not_modelled",
                    detail,
                    "Set refuelling_allowed to false, or plan the race as endurance.",
                )
            ],
        )

    available = _available(setup)
    race_laps = int(setup.race_laps or 0)
    if not available:
        plan = _empty_plan(
            setup,
            name,
            [
                _issue(
                    "no_legal_plan",
                    "No tyre sequence covers the race within the life and compound rules.",
                    "Raise a tyre's life, allow another stop, or lower the compound count.",
                )
            ],
        )
        return plan
    probe = score_stints(
        setup,
        [StintRequest(available[0].compound_id, race_laps)],
        name=name,
    )
    if probe.pace_base_sec is None:
        return probe
    base = probe.pace_base_sec
    scored: list[F1Plan] = []
    for stops in range(0, setup.max_stops + 1):
        length = stops + 1
        if length > race_laps:
            continue
        for combo in itertools.product(available, repeat=length):
            if _slick_rule_blocks(combo, setup.dry_min_compounds):
                continue
            costs = [_stint_cost(base, compound) for compound in combo]
            allocated = best_lap_split(
                race_laps,
                [int(compound.max_laps or 0) for compound in combo],
                costs,
            )
            if allocated is None:
                continue
            requests = [
                StintRequest(compound.compound_id, laps)
                for compound, laps in zip(combo, allocated, strict=True)
            ]
            scored.append(
                score_stints(setup, requests, name=name, candidates_checked=0)
            )

    checked = len(scored)
    feasible = [plan for plan in scored if plan.feasible]
    pool = feasible or scored
    if not pool:
        plan = _empty_plan(
            setup,
            name,
            [
                _issue(
                    "no_legal_plan",
                    "No tyre sequence covers the race within the life and compound rules.",
                    "Raise a tyre's life, allow another stop, or lower the compound count.",
                )
            ],
        )
        plan.candidates_checked = 0
        return plan

    winner = min(pool, key=_rank_key)
    winner.strategy_name = name
    winner.candidates_checked = checked
    if not winner.feasible and not any(
        issue.code == "no_legal_plan" for issue in winner.infeasibilities
    ):
        winner.infeasibilities.insert(
            0,
            _issue(
                "no_legal_plan",
                "No legal tyre sequence was faster than this rejected plan.",
                "Relax the failing rule, or edit the stints yourself.",
            ),
        )
        winner.summary = _summary(winner)
        winner.why = winner.infeasibilities[0].message
    return winner


def compare_f1(setup: F1Setup, scenarios: list[ScenarioRequest]) -> list[F1Plan]:
    """Rank the suggested plan and any named sequences the caller supplies."""
    rows = list(scenarios)
    if not any(row.stints is None for row in rows):
        rows = [ScenarioRequest("Suggested", None), *rows]
    plans: list[F1Plan] = []
    for row in rows:
        if row.stints is None:
            plan = best_f1_plan(setup, name=row.name or "Suggested")
        else:
            plan = score_stints(setup, row.stints, name=row.name)
        plans.append(plan)
    ranked = sorted(
        plans,
        key=lambda plan: (
            0 if plan.feasible else 1,
            plan.race_time_sec if plan.race_time_sec is not None else math.inf,
            plan.strategy_name,
        ),
    )
    leader = ranked[0] if ranked else None
    for index, plan in enumerate(ranked, start=1):
        plan.rank = index
        plan.preferred = index == 1 and plan.feasible
        plan.ranking_reason = _ranking_reason(plan, leader)
    return ranked


def _ranking_reason(plan: F1Plan, leader: F1Plan | None) -> str:
    if not plan.feasible:
        return plan.infeasibilities[0].message if plan.infeasibilities else "Not legal."
    if plan.preferred:
        return "Fastest legal plan under this file."
    if (
        leader is None
        or leader.race_time_sec is None
        or plan.race_time_sec is None
        or not leader.feasible
    ):
        return "Legal under this file."
    gap = plan.race_time_sec - leader.race_time_sec
    return f"Slower than the leading legal plan by {gap:.3f} s."


def _priced_losses(
    setup: F1Setup, stop_laps: list[int], sc: SafetyCarRequest
) -> list[float]:
    losses: list[float] = []
    normal = float(setup.pit_lane_loss_sec or 0.0)
    for lap in stop_laps:
        if sc.start_lap <= lap <= sc.end_lap:
            losses.append(sc.pit_loss_sec)
        else:
            losses.append(normal)
    return losses


def replan_f1_safety_car(
    plan: F1Plan,
    sc: SafetyCarRequest,
) -> SafetyCarResult:
    """Re-price pit loss under one safety-car window, and move one stop into it.

    Lap times under the safety car are not resimulated. A declared field lap
    delta is added to both clocks for every lap of the window, so it does not
    change the pit saving. Each rival stop inside the window removes the cheap
    pit delta from that saving. The caller supplies both numbers.
    """
    setup = plan.setup
    confidence = (
        "Deterministic pit-loss scenario. Safety-car lap times are not resimulated."
    )
    if not plan.feasible or plan.race_time_sec is None:
        summary = "The plan is not legal, so the safety car was not applied."
        return SafetyCarResult(
            original=plan,
            replanned=plan,
            original_race_time_sec=plan.race_time_sec,
            replanned_race_time_sec=plan.race_time_sec,
            time_saved_sec=0.0,
            stop_laps=list(plan.stop_laps),
            stops_moved=False,
            summary=summary,
            confidence="Not evaluated",
            assumptions=[summary],
        )
    race_laps = int(setup.race_laps or 0)
    if sc.pit_loss_sec < 0 or sc.field_lap_delta_sec < 0 or sc.rival_stops < 0:
        summary = (
            "Safety-car pit loss, the field lap delta, and rival stops "
            "must be zero or higher. This scenario was not evaluated."
        )
        return SafetyCarResult(
            original=plan,
            replanned=plan,
            original_race_time_sec=plan.race_time_sec,
            replanned_race_time_sec=plan.race_time_sec,
            time_saved_sec=0.0,
            stop_laps=list(plan.stop_laps),
            stops_moved=False,
            summary=summary,
            confidence="Not evaluated",
            assumptions=[summary],
        )
    if sc.start_lap < 1 or sc.end_lap < sc.start_lap or sc.end_lap > race_laps:
        summary = (
            f"Safety car laps must sit inside the race. "
            f"The window was {sc.start_lap}–{sc.end_lap} and the race is {race_laps} laps."
        )
        return SafetyCarResult(
            original=plan,
            replanned=plan,
            original_race_time_sec=plan.race_time_sec,
            replanned_race_time_sec=plan.race_time_sec,
            time_saved_sec=0.0,
            stop_laps=list(plan.stop_laps),
            stops_moved=False,
            summary=summary,
            confidence="Not evaluated",
            assumptions=[summary],
        )

    base_laps = [stint.laps for stint in plan.stints]
    compounds = [stint.compound_id for stint in plan.stints]
    trials = [tuple(base_laps)]
    if sc.pull_pit_into_sc:
        for index in range(len(base_laps) - 1):
            current = sum(base_laps[: index + 1])
            for target in range(sc.start_lap, sc.end_lap + 1):
                delta = target - current
                trial = list(base_laps)
                trial[index] += delta
                trial[index + 1] -= delta
                if trial[index] < 1 or trial[index + 1] < 1:
                    continue
                trials.append(tuple(trial))

    best: F1Plan | None = None
    best_laps: tuple[int, ...] | None = None
    best_key: tuple[float, int, tuple[int, ...]] | None = None
    seen: set[tuple[int, ...]] = set()
    for trial in trials:
        if trial in seen:
            continue
        seen.add(trial)
        stop_laps: list[int] = []
        running = 0
        for laps in trial[:-1]:
            running += laps
            stop_laps.append(running)
        losses = _priced_losses(setup, stop_laps, sc)
        requests = [
            StintRequest(compound, laps)
            for compound, laps in zip(compounds, trial, strict=True)
        ]
        candidate = score_stints(
            setup,
            requests,
            name=f"{plan.strategy_name} + SC",
            pit_losses_sec=losses,
        )
        if not candidate.feasible or candidate.race_time_sec is None:
            continue
        movement = sum(
            abs(left - right) for left, right in zip(trial, base_laps, strict=True)
        )
        key = (candidate.race_time_sec, movement, trial)
        if best_key is None or key < best_key:
            best = candidate
            best_laps = trial
            best_key = key

    if best is None or best.race_time_sec is None or best_laps is None:
        summary = "No legal safety-car pit option was found."
        return SafetyCarResult(
            original=plan,
            replanned=plan,
            original_race_time_sec=plan.race_time_sec,
            replanned_race_time_sec=plan.race_time_sec,
            time_saved_sec=0.0,
            stop_laps=list(plan.stop_laps),
            stops_moved=False,
            summary=summary,
            confidence=confidence,
            assumptions=[confidence],
        )

    window_laps = sc.end_lap - sc.start_lap + 1
    field_ms = round(sc.field_lap_delta_sec * 1000) * window_laps
    original_ms = round(plan.race_time_sec * 1000) + field_ms
    replanned_ms = round(best.race_time_sec * 1000) + field_ms
    pit_saved_ms = round(plan.race_time_sec * 1000) - round(best.race_time_sec * 1000)
    green = float(setup.pit_lane_loss_sec or 0.0)
    cheap_ms = max(0, round(green * 1000) - round(sc.pit_loss_sec * 1000))
    in_window = sum(1 for lap in best.stop_laps if sc.start_lap <= lap <= sc.end_lap)
    matched = min(sc.rival_stops, in_window)
    rival_ms = cheap_ms * matched
    saved = (pit_saved_ms - rival_ms) / 1000
    pit_saved = pit_saved_ms / 1000
    field_cost = field_ms / 1000
    moved = tuple(best_laps) != tuple(base_laps)
    if moved and best.stop_laps:
        summary = (
            f"Move a stop to lap {best.stop_laps[0] if len(best.stop_laps) == 1 else best.stop_laps}, "
            f"inside the safety-car window (laps {sc.start_lap}–{sc.end_lap}). "
            f"Estimated time saved: {pit_saved:.3f} s."
        )
    elif best.stop_laps and any(
        sc.start_lap <= lap <= sc.end_lap for lap in best.stop_laps
    ):
        summary = (
            f"Pit on lap {best.stop_laps[0]}, which is inside the safety-car window "
            f"(laps {sc.start_lap}–{sc.end_lap}). "
            f"That stop costs {sc.pit_loss_sec:.1f} s instead of {setup.pit_lane_loss_sec:.1f} s, "
            f"saving {pit_saved:.3f} s. The tyre sequence stays the same."
        )
    else:
        summary = (
            f"No planned stop sits inside laps {sc.start_lap}–{sc.end_lap}, "
            "and moving a stop into that window would run a tyre past its life. "
            "Estimated time saved: 0 s."
        )
    if field_cost:
        summary += (
            f" The field loses {sc.field_lap_delta_sec:.3f} s on each of the "
            f"{window_laps} laps in the window, {field_cost:.3f} s on both clocks."
        )
    if rival_ms:
        stop_word = "stop" if matched == 1 else "stops"
        verb = "takes" if matched == 1 else "take"
        summary += (
            f" {matched} rival {stop_word} inside the window "
            f"{verb} back {rival_ms / 1000:.3f} s, "
            f"so the net saving against that rival is {saved:.3f} s."
        )
    window_note = (
        f"One safety car from lap {sc.start_lap} to lap {sc.end_lap}. "
        f"A stop in that window costs {sc.pit_loss_sec:.1f} s."
    )
    if field_cost or rival_ms:
        window_note += (
            " Field lap delta and rival stops are caller-declared offsets, "
            "not a measured circuit multiplier."
        )
    best.summary = summary
    best.assumptions = [*best.assumptions, confidence, window_note]
    return SafetyCarResult(
        original=plan,
        replanned=best,
        original_race_time_sec=original_ms / 1000,
        replanned_race_time_sec=replanned_ms / 1000,
        time_saved_sec=saved,
        stop_laps=list(best.stop_laps),
        stops_moved=moved,
        summary=summary,
        confidence=confidence,
        assumptions=list(best.assumptions[-2:]),
    )
