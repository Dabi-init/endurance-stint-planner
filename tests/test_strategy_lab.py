"""Adversarial tests for the decision-support claims made by the lab."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.models import Driver, DriverCategory, RaceConfig
from engine.planner import (
    DEFAULT_PRESET,
    PlanOptions,
    compute_plan,
    load_preset,
    pit_stop_duration_sec,
)
from engine.regulations import check_compliance
from engine.safety_car import SafetyCarConfig, replan_with_safety_car
from engine.simulation import simulate_plan
from engine.strategy import compare_strategies
from engine.telemetry import calibrate_telemetry

ROOT = Path(__file__).resolve().parent.parent


def test_refuel_flow_materially_changes_race_outcome() -> None:
    base = load_preset(DEFAULT_PRESET)
    slow = RaceConfig.from_dict(base.to_dict())
    slow.refuel_rate_liters_per_sec = 0.5
    fast = RaceConfig.from_dict(base.to_dict())
    fast.refuel_rate_liters_per_sec = 10.0

    slow_plan = compute_plan(slow)
    fast_plan = compute_plan(fast)

    assert slow_plan.total_pit_time_sec > fast_plan.total_pit_time_sec
    assert slow_plan.predicted_laps < fast_plan.predicted_laps


def test_final_stint_uses_exact_need_plus_reserve() -> None:
    config = load_preset(DEFAULT_PRESET)
    plan = compute_plan(config)
    final = plan.stints[-1]
    reserve = config.regulations.fuel_safety_laps * config.fuel_consumption_per_lap

    assert final.fuel_load_liters == pytest.approx(final.fuel_used_liters + reserve)
    assert final.fuel_load_liters < config.fuel_tank_liters


def test_duplicate_display_names_keep_independent_rules() -> None:
    base = load_preset(DEFAULT_PRESET)
    config = RaceConfig.from_dict(base.to_dict())
    config.drivers = [
        Driver("Same", DriverCategory.PRO),
        Driver("Same", DriverCategory.BRONZE, pace_delta_sec=0.8),
    ]
    config.regulations.bronze_min_drive_min = 120.0

    plan = compute_plan(config)
    compliance = check_compliance(plan)

    assert len({driver.id for driver in config.drivers}) == 2
    assert len(plan.driver_totals_by_id()) == 2
    assert len(plan.driver_totals()) == 2
    assert compliance.driver_results[0].total_drive_min != (
        compliance.driver_results[1].total_drive_min
    )
    assert compliance.all_passed


def test_service_model_distinguishes_parallel_and_sequential_work() -> None:
    base = load_preset(DEFAULT_PRESET)
    parallel = pit_stop_duration_sec(
        base, True, fuel_added_liters=80.0, change_driver=True
    )
    sequential_config = RaceConfig.from_dict(base.to_dict())
    sequential_config.services_parallel = False
    sequential = pit_stop_duration_sec(
        sequential_config,
        True,
        fuel_added_liters=80.0,
        change_driver=True,
    )

    assert sequential > parallel
    assert parallel == pytest.approx(
        base.pit_stop_time_loss_sec
        + max(
            80.0 / base.refuel_rate_liters_per_sec,
            base.tyre_change_time_sec,
            base.driver_change_time_sec,
        )
    )


def test_sc_pace_multiplier_is_not_cosmetic() -> None:
    original = compute_plan(load_preset(DEFAULT_PRESET))
    mild = replan_with_safety_car(
        original,
        SafetyCarConfig(120.0, 20.0, lap_time_multiplier=1.1),
    )
    severe = replan_with_safety_car(
        original,
        SafetyCarConfig(120.0, 20.0, lap_time_multiplier=3.0),
    )

    assert mild.replanned.predicted_laps > severe.replanned.predicted_laps
    assert mild.replanned.total_fuel_used_liters != pytest.approx(
        severe.replanned.total_fuel_used_liters
    )


def test_sc_reduced_transit_applies_to_at_most_one_stop() -> None:
    original = compute_plan(load_preset(DEFAULT_PRESET))
    scenario = replan_with_safety_car(
        original,
        SafetyCarConfig(
            deploy_min=40.0,
            duration_min=240.0,
            lap_time_multiplier=1.4,
            sc_pit_loss_sec=20.0,
        ),
    )

    tagged = [
        stint
        for stint in scenario.replanned.stints
        if "SC pit-lane transit" in stint.notes
    ]
    assert len(tagged) <= 1


def test_synthetic_telemetry_calibrates_but_stays_evidence_level_c() -> None:
    path = ROOT / "examples" / "spa_6h_synthetic.csv"
    calibration = calibrate_telemetry(
        path.read_text(encoding="utf-8"),
        source_name=path.name,
        is_synthetic=True,
    )

    assert calibration.quality_score >= 85
    assert calibration.evidence_level == "C"
    assert calibration.fuel_burn_median_l_per_lap == pytest.approx(2.6)
    assert calibration.median_lap_time_sec is not None
    assert calibration.usable_for_strategy


def test_missing_fuel_is_reported_and_not_invented() -> None:
    csv_text = "lap,lap_time_sec\n1,120.0\n2,120.5\n3,121.0\n"
    calibration = calibrate_telemetry(csv_text)

    assert calibration.fuel_burn_median_l_per_lap is None
    assert not calibration.usable_for_strategy
    assert any("fuel" in finding.message.lower() for finding in calibration.findings)


def test_uncertainty_simulation_is_seeded_and_reproducible() -> None:
    config = load_preset(DEFAULT_PRESET)
    options = PlanOptions(name="Balanced")

    first = simulate_plan(config, options, iterations=40, seed=7)
    second = simulate_plan(config, options, iterations=40, seed=7)

    assert first == second


def test_strategy_ranking_is_complete_and_explainable() -> None:
    comparison = compare_strategies(
        load_preset(DEFAULT_PRESET),
        iterations=30,
    )

    assert [outcome.rank for outcome in comparison.outcomes] == [1, 2, 3]
    assert sum(outcome.preferred for outcome in comparison.outcomes) == 1
    assert all(outcome.ranking_reason for outcome in comparison.outcomes)
    assert comparison.preferred.plan.is_feasible
    assert len({outcome.simulation.seed for outcome in comparison.outcomes}) == 1
