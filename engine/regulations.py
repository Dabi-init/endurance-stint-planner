"""Driver-rule checks with stable identities and explicit pass/fail evidence."""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.models import (
    Driver,
    DriverRegulations,
    PlanResult,
    RaceConfig,
    Stint,
    format_duration,
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
        return all(check.passed for check in self.checks)


@dataclass
class ComplianceReport:
    driver_results: list[DriverCompliance] = field(default_factory=list)
    stint_violations: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return not self.stint_violations and all(
            driver.all_passed for driver in self.driver_results
        )


def _stint_cap(regulations: DriverRegulations, driver: Driver) -> float:
    limits = [
        value
        for value in (
            regulations.max_continuous_stint_min,
            regulations.max_stint_for_category(driver.category),
        )
        if value > 0
    ]
    return min(limits) if limits else 0.0


def _driver_stint_violations(
    stints: list[Stint],
    driver: Driver,
    regulations: DriverRegulations,
) -> list[str]:
    cap = _stint_cap(regulations, driver)
    if cap <= 0:
        return []
    return [
        (
            f"Stint {stint.stint_number}: {driver.name} [{driver.id}] drove "
            f"{format_duration(stint.duration_min)}, exceeding the configured "
            f"{format_duration(cap)} continuous limit."
        )
        for stint in stints
        if stint.driver.id == driver.id and stint.duration_min > cap + 0.5
    ]


def _build_driver_checks(
    driver: Driver,
    driven_min: float,
    regulations: DriverRegulations,
    race_duration_min: float,
    stint_failures: list[str],
) -> list[RuleCheck]:
    cap = _stint_cap(regulations, driver)
    checks = [
        RuleCheck(
            "max_continuous_stint",
            (
                f"{driver.category.value} continuous stint limit: "
                f"{format_duration(cap)}"
                if cap > 0
                else "No configured continuous stint limit"
            ),
            not stint_failures,
            (
                stint_failures[0]
                if stint_failures
                else "Every assigned stint is within the configured limit."
            ),
        )
    ]

    minimum = regulations.min_drive_for_category(driver.category)
    if minimum > 0:
        passed = driven_min >= minimum - 0.5
        checks.append(
            RuleCheck(
                "min_total_drive",
                (
                    f"{driver.category.value} minimum total drive: "
                    f"{format_duration(minimum)}"
                ),
                passed,
                (
                    f"Driven {format_duration(driven_min)}."
                    if passed
                    else (
                        f"Short by {format_duration(minimum - driven_min)}; "
                        f"driven {format_duration(driven_min)}."
                    )
                ),
            )
        )

    maximum = regulations.max_total_drive_min
    if maximum > 0:
        passed = driven_min <= maximum + 0.5
        checks.append(
            RuleCheck(
                "max_total_drive",
                f"Maximum total drive: {format_duration(maximum)}",
                passed,
                (
                    f"Driven {format_duration(driven_min)}."
                    if passed
                    else (
                        f"Over by {format_duration(driven_min - maximum)}; "
                        f"driven {format_duration(driven_min)}."
                    )
                ),
            )
        )

    share = 100.0 * driven_min / race_duration_min if race_duration_min > 0 else 0.0
    checks.append(
        RuleCheck(
            "drive_share",
            "Allocated race-clock share",
            True,
            f"{format_duration(driven_min)} ({share:.1f}% of scheduled race time).",
        )
    )
    return checks


def check_compliance(plan: PlanResult) -> ComplianceReport:
    """Evaluate each configured driver independently, including duplicate names."""
    config = plan.config
    totals = plan.driver_totals_by_id()
    driver_results: list[DriverCompliance] = []
    all_stint_failures: list[str] = []

    for driver in config.drivers:
        failures = _driver_stint_violations(plan.stints, driver, config.regulations)
        all_stint_failures.extend(failures)
        driven = totals.get(driver.id, 0.0)
        driver_results.append(
            DriverCompliance(
                driver=driver,
                total_drive_min=driven,
                checks=_build_driver_checks(
                    driver,
                    driven,
                    config.regulations,
                    config.race_duration_min,
                    failures,
                ),
            )
        )
    return ComplianceReport(driver_results, all_stint_failures)


def _estimate_for_driver(
    estimates: dict[str, float],
    driver: Driver,
) -> float:
    """Accept stable IDs and retain name fallback for older API callers."""
    if driver.id in estimates:
        return estimates[driver.id]
    return estimates.get(driver.name, 0.0)


def preflight_infeasibility_checks(
    config: RaceConfig,
    driver_totals_estimate: dict[str, float] | None = None,
) -> list[str]:
    """Return rule conflicts that can be established from configured evidence."""
    reasons: list[str] = []
    drivers = config.drivers
    regulations = config.regulations
    race_min = config.race_duration_min

    if not drivers:
        return ["At least one driver is required."]

    required_total = sum(
        max(regulations.min_drive_for_category(driver.category), 0.0)
        for driver in drivers
    )
    if required_total > race_min + 0.5:
        reasons.append(
            f"Configured per-driver minimums total "
            f"{format_duration(required_total)}, longer than the "
            f"{format_duration(race_min)} race."
        )

    if regulations.max_total_drive_min > 0:
        available_total = regulations.max_total_drive_min * len(drivers)
        if available_total < race_min - 1.0:
            reasons.append(
                f"Configured maximum drive capacity is "
                f"{format_duration(available_total)}, shorter than the "
                f"{format_duration(race_min)} race clock."
            )

    if driver_totals_estimate is not None:
        for driver in drivers:
            driven = _estimate_for_driver(driver_totals_estimate, driver)
            minimum = regulations.min_drive_for_category(driver.category)
            if minimum > 0 and driven < minimum - 0.5:
                reasons.append(
                    f"{driver.category.value} driver {driver.name} "
                    f"[{driver.id}] is short of the "
                    f"{format_duration(minimum)} minimum by "
                    f"{format_duration(minimum - driven)}."
                )
            maximum = regulations.max_total_drive_min
            if maximum > 0 and driven > maximum + 0.5:
                reasons.append(
                    f"Driver {driver.name} [{driver.id}] exceeds the "
                    f"{format_duration(maximum)} total-drive maximum by "
                    f"{format_duration(driven - maximum)}."
                )
    return reasons
