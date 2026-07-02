"""Strategy recommendations and calculated metrics from plan + circuit data."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.circuits import Circuit, get_circuit
from engine.models import DriverCategory, PlanResult, RaceConfig, format_duration
from engine.planner import fuel_limited_laps


@dataclass
class StrategyInsight:
    category: str
    title: str
    detail: str
    priority: str = "medium"

    def icon(self) -> str:
        return {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(self.priority, "⚪")


@dataclass
class CalculatedMetrics:
    avg_stint_laps: float = 0.0
    avg_stint_min: float = 0.0
    fuel_limited_stint_pct: float = 0.0
    tyre_limited_stint_pct: float = 0.0
    fuel_laps_geometry: int = 0
    tyre_laps_geometry: int = 0
    fuel_tyre_gap_laps: int = 0
    estimated_deg_per_lap_sec: float = 0.0
    estimated_pace_loss_final_lap_sec: float = 0.0
    pit_stops_per_hour: float = 0.0
    limiting_factor: str = ""

    def to_dict(self) -> dict:
        return {
            "avg_stint_laps": round(self.avg_stint_laps, 1),
            "avg_stint_min": round(self.avg_stint_min, 1),
            "fuel_limited_stint_pct": round(self.fuel_limited_stint_pct, 0),
            "tyre_limited_stint_pct": round(self.tyre_limited_stint_pct, 0),
            "fuel_laps_geometry": self.fuel_laps_geometry,
            "tyre_laps_geometry": self.tyre_laps_geometry,
            "fuel_tyre_gap_laps": self.fuel_tyre_gap_laps,
            "estimated_deg_per_lap_sec": round(self.estimated_deg_per_lap_sec, 3),
            "estimated_pace_loss_final_lap_sec": round(self.estimated_pace_loss_final_lap_sec, 2),
            "pit_stops_per_hour": round(self.pit_stops_per_hour, 2),
            "limiting_factor": self.limiting_factor,
        }


@dataclass
class StrategyReport:
    circuit: Circuit | None
    metrics: CalculatedMetrics
    insights: list[StrategyInsight] = field(default_factory=list)
    race_approach_summary: str = ""

    @property
    def high_priority(self) -> list[StrategyInsight]:
        return [i for i in self.insights if i.priority == "high"]


def compute_metrics(plan: PlanResult, circuit: Circuit | None) -> CalculatedMetrics:
    config = plan.config
    stints = plan.stints
    if not stints:
        return CalculatedMetrics()

    fuel_laps = fuel_limited_laps(config)
    tyre_laps = config.tyre_life_laps
    n = len(stints)
    fuel_count = sum(1 for s in stints if "Fuel" in s.limiting_factor)
    tyre_count = sum(1 for s in stints if "Tyre" in s.limiting_factor)

    avg_laps = sum(s.laps for s in stints) / n
    avg_min = sum(s.duration_min for s in stints) / n
    deg = circuit.deg_per_lap_sec if circuit else 0.07
    final_stint = stints[-1]
    pace_loss = deg * final_stint.tyre_age_at_end_laps

    race_hours = max(config.race_duration_hours, 0.1)
    stops_per_hour = plan.total_pit_stops / race_hours

    return CalculatedMetrics(
        avg_stint_laps=avg_laps,
        avg_stint_min=avg_min,
        fuel_limited_stint_pct=100.0 * fuel_count / n,
        tyre_limited_stint_pct=100.0 * tyre_count / n,
        fuel_laps_geometry=fuel_laps,
        tyre_laps_geometry=tyre_laps,
        fuel_tyre_gap_laps=abs(fuel_laps - tyre_laps),
        estimated_deg_per_lap_sec=deg,
        estimated_pace_loss_final_lap_sec=pace_loss,
        pit_stops_per_hour=stops_per_hour,
        limiting_factor=(
            "Fuel" if fuel_laps < tyre_laps
            else "Tyre" if tyre_laps < fuel_laps
            else "Balanced"
        ),
    )


def _tyre_insights(
    plan: PlanResult,
    circuit: Circuit | None,
    metrics: CalculatedMetrics,
) -> list[StrategyInsight]:
    insights: list[StrategyInsight] = []
    if not plan.stints or not circuit:
        return insights

    if circuit.tyre_wear == "High":
        insights.append(
            StrategyInsight(
                category="Tyre Strategy",
                title="High tyre wear circuit",
                detail=(
                    f"{circuit.name} is classified as high tyre wear. "
                    f"Model caps stints at {metrics.tyre_laps_geometry} laps — "
                    f"consider fresh sets every stop and avoid extending beyond "
                    f"lap {metrics.tyre_laps_geometry - 2} unless saving a pit."
                ),
                priority="high",
            )
        )
    elif circuit.tyre_wear == "Low" and metrics.limiting_factor == "Fuel":
        insights.append(
            StrategyInsight(
                category="Tyre Strategy",
                title="Fuel-limited — tyre management less critical",
                detail=(
                    f"At {circuit.name}, fuel range ({metrics.fuel_laps_geometry} laps) "
                    f"binds before tyre life ({metrics.tyre_laps_geometry} laps). "
                    "Focus on consistent fuel usage; one compound may suffice."
                ),
                priority="low",
            )
        )

    if metrics.tyre_limited_stint_pct >= 60:
        insights.append(
            StrategyInsight(
                category="Tyre Strategy",
                title="Tyre-limited race geometry",
                detail=(
                    f"{metrics.tyre_limited_stint_pct:.0f}% of stints are tyre-limited. "
                    f"Estimated degradation ~{metrics.estimated_deg_per_lap_sec:.2f}s/lap — "
                    f"~{metrics.estimated_pace_loss_final_lap_sec:.1f}s loss on the "
                    f"final lap of a typical stint."
                ),
                priority="medium",
            )
        )

    if metrics.fuel_tyre_gap_laps <= 2:
        insights.append(
            StrategyInsight(
                category="Tyre Strategy",
                title="Tight fuel/tyre crossover",
                detail=(
                    f"Fuel and tyre caps differ by only {metrics.fuel_tyre_gap_laps} lap(s). "
                    "Small changes in consumption or track temperature could shift "
                    "the limiting factor mid-race — monitor both."
                ),
                priority="medium",
            )
        )

    return insights


def _pit_window_insights(plan: PlanResult, metrics: CalculatedMetrics) -> list[StrategyInsight]:
    insights: list[StrategyInsight] = []
    if len(plan.stints) < 2:
        return insights

    first = plan.stints[0]
    window_start = max(first.laps - 3, 1)
    window_end = first.laps
    pit_min = plan.config.pit_stop_time_loss_sec

    insights.append(
        StrategyInsight(
            category="Pit Windows",
            title=f"First stop window: lap {window_start}–{window_end}",
            detail=(
                f"First stint geometry is {first.laps} laps (~"
                f"{format_duration(first.duration_min)}). "
                f"Undercut/cover windows cluster around lap {window_end - 1}–{window_end + 1} "
                f"assuming {pit_min:.0f}s pit loss. "
                "Adjust ±2 laps for traffic or class position."
            ),
            priority="medium",
        )
    )

    if len(plan.stints) >= 3:
        second = plan.stints[1]
        insights.append(
            StrategyInsight(
                category="Pit Windows",
                title=f"Second stop reference: lap {first.laps + second.laps - 2}–{first.laps + second.laps}",
                detail=(
                    "Plan a flexible ±1-lap band on subsequent stops. "
                    "Crossover value depends on competitor pit timing (not modelled)."
                ),
                priority="low",
            )
        )

    return insights


def _driver_insights(plan: PlanResult) -> list[StrategyInsight]:
    insights: list[StrategyInsight] = []
    totals = plan.driver_totals()
    config = plan.config
    regs = config.regulations

    for driver in config.drivers:
        driven = totals.get(driver.name, 0.0)
        min_req = regs.min_drive_for_category(driver.category)
        if min_req > 0:
            margin = driven - min_req
            if margin < 15:
                insights.append(
                    StrategyInsight(
                        category="Driver Rotation",
                        title=f"{driver.name}: tight on minimum drive",
                        detail=(
                            f"{driver.category.value} minimum is "
                            f"{format_duration(min_req)}; plan allocates "
                            f"{format_duration(driven)} (margin "
                            f"{format_duration(max(margin, 0))}). "
                            "Avoid unexpected extra stops that could drop them below quota."
                        ),
                        priority="high" if margin < 5 else "medium",
                    )
                )
            elif margin > 60 and driver.category == DriverCategory.PRO:
                insights.append(
                    StrategyInsight(
                        category="Driver Rotation",
                        title=f"{driver.name}: could absorb longer stints",
                        detail=(
                            f"Pro driver has {format_duration(driven)} allocated with "
                            "comfortable regulatory margin — consider longer opening "
                            "or pre-FCY stints to protect race rhythm."
                        ),
                        priority="low",
                    )
                )

    silver_drivers = [d for d in config.drivers if d.category == DriverCategory.SILVER]
    for driver in silver_drivers:
        if totals.get(driver.name, 0.0) < config.race_duration_min * 0.12:
            insights.append(
                StrategyInsight(
                    category="Driver Rotation",
                    title=f"{driver.name}: limited seat time",
                    detail=(
                        f"Silver driver has only {format_duration(totals.get(driver.name, 0.0))} "
                        "in the current rotation. Ensure at least one double-stint "
                        "or swap earlier if they are your night/rain driver."
                    ),
                    priority="medium",
                )
            )

    return insights


def _sc_insights(plan: PlanResult, circuit: Circuit | None) -> list[StrategyInsight]:
    insights: list[StrategyInsight] = []
    if not circuit:
        return insights

    risk = circuit.sc_risk
    race_min = plan.config.race_duration_min
    mid_race = race_min * 0.4

    if risk == "High":
        insights.append(
            StrategyInsight(
                category="Safety Car",
                title="Elevated SC probability at this circuit",
                detail=(
                    f"{circuit.name} is rated high SC risk. Pre-brief a "
                    f"replan from ~{format_duration(mid_race)} and keep fuel "
                    "to pit under SC without short-filling the next stint."
                ),
                priority="high",
            )
        )
    elif risk == "Medium":
        insights.append(
            StrategyInsight(
                category="Safety Car",
                title="Moderate SC risk — have a Plan B",
                detail=(
                    "Use the What-If tab to test SC at 35–45% race distance. "
                    "Pitting under SC typically saves 20–30s vs green-flag stops."
                ),
                priority="medium",
            )
        )
    else:
        insights.append(
            StrategyInsight(
                category="Safety Car",
                title="Low historical SC risk",
                detail=(
                    "Base plan assumes green-flag racing. SC gains are opportunistic "
                    "rather than core strategy at this circuit."
                ),
                priority="low",
            )
        )

    return insights


def _race_approach_summary(
    plan: PlanResult,
    circuit: Circuit | None,
    metrics: CalculatedMetrics,
) -> str:
    if not plan.is_feasible:
        return (
            "Resolve infeasibility before race approach can be summarised. "
            "Check driver minimums and fuel/tyre geometry."
        )

    circuit_name = circuit.name if circuit else "this circuit"
    wear = circuit.tyre_wear if circuit else "Medium"
    parts = [
        f"**{plan.config.race_name}** at {circuit_name}: "
        f"{len(plan.stints)} stints, {plan.total_pit_stops} pit stops, "
        f"~{plan.predicted_laps} laps.",
        f"Average stint **{metrics.avg_stint_laps:.0f} laps** "
        f"({format_duration(metrics.avg_stint_min)}). "
        f"Race is **{metrics.limiting_factor.lower()}-limited** on paper.",
    ]

    if wear == "High":
        parts.append(
            "Prioritise tyre preservation and punctual stops — "
            "extending stints here typically costs more lap time than an extra stop."
        )
    elif metrics.limiting_factor == "Fuel":
        parts.append(
            "Manage fuel delta to the model each stint; tyre compound choice is secondary."
        )
    else:
        parts.append(
            "Balance driver rotation with stable pit cadence; "
            "regulation compliance is already reflected in the plan."
        )

    return " ".join(parts)


def generate_strategy_report(
    plan: PlanResult,
    circuit_id: str | None = None,
) -> StrategyReport:
    """Build recommendations entirely from plan maths and circuit profile."""
    circuit = get_circuit(circuit_id or getattr(plan.config, "circuit_id", None))
    metrics = compute_metrics(plan, circuit)

    insights: list[StrategyInsight] = []
    insights.extend(_tyre_insights(plan, circuit, metrics))
    insights.extend(_pit_window_insights(plan, metrics))
    insights.extend(_driver_insights(plan))
    insights.extend(_sc_insights(plan, circuit))

    priority_order = {"high": 0, "medium": 1, "low": 2}
    insights.sort(key=lambda i: priority_order.get(i.priority, 3))

    return StrategyReport(
        circuit=circuit,
        metrics=metrics,
        insights=insights,
        race_approach_summary=_race_approach_summary(plan, circuit, metrics),
    )