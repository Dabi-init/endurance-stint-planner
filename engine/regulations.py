"""Driver regulation compliance engine — structured pass/fail per rule."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.models import (
    Driver,
    DriverCategory,
    DriverRegulations,
    PlanResult,
    RaceConfig,
    Stint,
    format_duration,
    format_duration_from_hours,
)


@dataclass
class RuleCheck:
    rule_id: str
    rule_text: str
    passed: bool
    detail: str = ""

    def status_icon(self) -> str:
        return "✅" if self.passed else "❌"


@dataclass
class DriverCompliance:
    driver: Driver
    total_drive_min: float
    checks: list[RuleCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


@dataclass
class ComplianceReport:
    driver_results: list[DriverCompliance] = field(default_factory=list)
    stint_violations: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        if self.stint_violations:
            return False
        return all(d.all_passed for d in self.driver_results)


def _max_stint_violations(
    stints: list[Stint],
    regulations: DriverRegulations,
) -> list[str]:
    violations: list[str] = []
    for stint in stints:
        cap = regulations.max_stint_for_category(stint.driver.category)
        if cap > 0 and stint.duration_min > cap + 0.5:
            violations.append(
                f"Stint {stint.stint_number}: {stint.driver.name} drove "
                f"{format_duration(stint.duration_min)} — exceeds "
                f"{stint.driver.category.value} max continuous stint "
                f"of {format_duration(cap)}."
            )
    return violations


def _build_driver_checks(
    driver: Driver,
    driven_min: float,
    regulations: DriverRegulations,
    race_duration_min: float,
) -> list[RuleCheck]:
    checks: list[RuleCheck] = []

    max_stint_cap = regulations.max_stint_for_category(driver.category)
    checks.append(
        RuleCheck(
            rule_id="max_continuous_stint",
            rule_text=(
                f"{driver.category.value} maximum continuous stint: "
                f"{format_duration(max_stint_cap)}"
            ),
            passed=True,
            detail="Validated per-stint in plan.",
        )
    )

    min_required = regulations.min_drive_for_category(driver.category)
    if min_required > 0:
        passed = driven_min >= min_required - 0.5
        shortfall = max(0.0, min_required - driven_min)
        checks.append(
            RuleCheck(
                rule_id="min_total_drive",
                rule_text=(
                    f"{driver.category.value} minimum total drive time: "
                    f"{format_duration(min_required)}"
                ),
                passed=passed,
                detail=(
                    f"Driven {format_duration(driven_min)}."
                    if passed
                    else (
                        f"Short by {format_duration(shortfall)} "
                        f"(driven {format_duration(driven_min)})."
                    )
                ),
            )
        )

    if regulations.max_total_drive_min > 0:
        passed = driven_min <= regulations.max_total_drive_min + 0.5
        excess = max(0.0, driven_min - regulations.max_total_drive_min)
        checks.append(
            RuleCheck(
                rule_id="max_total_drive",
                rule_text=(
                    f"Maximum total drive time per driver: "
                    f"{format_duration(regulations.max_total_drive_min)}"
                ),
                passed=passed,
                detail=(
                    f"Driven {format_duration(driven_min)}."
                    if passed
                    else (
                        f"Over by {format_duration(excess)} "
                        f"(driven {format_duration(driven_min)})."
                    )
                ),
            )
        )

    if regulations.min_total_drive_min > 0 and driver.category == DriverCategory.PRO:
        passed = driven_min >= regulations.min_total_drive_min - 0.5
        checks.append(
            RuleCheck(
                rule_id="pro_min_drive",
                rule_text=(
                    f"Pro minimum total drive: "
                    f"{format_duration(regulations.min_total_drive_min)}"
                ),
                passed=passed,
                detail=f"Driven {format_duration(driven_min)}.",
            )
        )

    pct = 100.0 * driven_min / race_duration_min if race_duration_min > 0 else 0.0
    checks.append(
        RuleCheck(
            rule_id="drive_share",
            rule_text=f"Drive share of {format_duration_from_hours(race_duration_min / 60):}",
            passed=True,
            detail=f"{format_duration(driven_min)} ({pct:.1f}% of race).",
        )
    )

    return checks


def check_compliance(plan: PlanResult) -> ComplianceReport:
    """Return structured pass/fail compliance for each driver and rule."""
    config = plan.config
    regulations = config.regulations
    totals = plan.driver_totals()
    race_min = config.race_duration_min

    driver_results: list[DriverCompliance] = []
    for driver in config.drivers:
        driven = totals.get(driver.name, 0.0)
        checks = _build_driver_checks(driver, driven, regulations, race_min)
        driver_results.append(
            DriverCompliance(driver=driver, total_drive_min=driven, checks=checks)
        )

    stint_violations = _max_stint_violations(plan.stints, regulations)
    return ComplianceReport(
        driver_results=driver_results,
        stint_violations=stint_violations,
    )


def preflight_infeasibility_checks(
    config: RaceConfig,
    driver_totals_estimate: dict[str, float] | None = None,
) -> list[str]:
    """
    Quick feasibility messages before or after planning.
    Returns human-readable reason strings (not Infeasibility objects).
    """
    reasons: list[str] = []
    regs = config.regulations
    race_min = config.race_duration_min
    n_drivers = len(config.drivers)

    if n_drivers < 1:
        reasons.append("At least one driver is required.")
        return reasons

    bronze_drivers = [d for d in config.drivers if d.category == DriverCategory.BRONZE]
    if bronze_drivers and regs.bronze_min_drive_min > 0:
        bronze_required = regs.bronze_min_drive_min * len(bronze_drivers)
        if bronze_required > race_min + 0.5:
            reasons.append(
                f"Bronze minimum of {format_duration(regs.bronze_min_drive_min)} "
                f"per driver cannot be satisfied: race is only "
                f"{format_duration(race_min)}."
            )

        if driver_totals_estimate:
            for driver in bronze_drivers:
                driven = driver_totals_estimate.get(driver.name, 0.0)
                if driven < regs.bronze_min_drive_min - 0.5:
                    shortfall = regs.bronze_min_drive_min - driven
                    reasons.append(
                        f"Bronze driver {driver.name} minimum of "
                        f"{format_duration(regs.bronze_min_drive_min)} cannot be "
                        f"satisfied: only {format_duration(driven)} allocated "
                        f"(short {format_duration(shortfall)})."
                    )

    if regs.max_total_drive_min > 0 and n_drivers > 0:
        min_needed = race_min / n_drivers
        if regs.max_total_drive_min < min_needed - 1.0:
            reasons.append(
                f"Max drive cap {format_duration(regs.max_total_drive_min)} per "
                f"driver is too low for a {format_duration(race_min)} race with "
                f"{n_drivers} drivers (need ~{format_duration(min_needed)} each)."
            )

    return reasons