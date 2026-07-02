"""Unit tests for the endurance stint planning engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.models import Driver, DriverCategory, DriverRegulations, RaceConfig
from engine.planner import (
    DEFAULT_PRESET,
    compute_plan,
    compute_plan_with_tyre_life,
    fuel_limited_laps,
    load_preset,
    list_presets,
    validate_config,
)
from engine.regulations import check_compliance
from engine.safety_car import SafetyCarConfig, replan_with_safety_car

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"


def _base_config(**overrides) -> RaceConfig:
    regs = DriverRegulations(
        pro_max_continuous_stint_min=120.0,
        silver_max_continuous_stint_min=90.0,
        bronze_max_continuous_stint_min=65.0,
        bronze_min_drive_min=0.0,
        fuel_safety_laps=1,
    )
    defaults = dict(
        race_name="Test Race",
        race_duration_hours=6.0,
        base_lap_time_sec=120.0,
        fuel_tank_liters=100.0,
        fuel_consumption_per_lap=2.9,
        pit_stop_time_loss_sec=55.0,
        refuel_rate_liters_per_sec=2.5,
        tyre_life_laps=28,
        tyre_change_time_sec=18.0,
        drivers=[
            Driver("Pro1", DriverCategory.PRO, 0.0),
            Driver("Silver1", DriverCategory.SILVER, 0.5),
            Driver("Bronze1", DriverCategory.BRONZE, 1.0),
        ],
        regulations=regs,
    )
    defaults.update(overrides)
    return RaceConfig(**defaults)


class TestPresetLoading:
    def test_list_presets_includes_default(self):
        presets = list_presets()
        assert DEFAULT_PRESET in presets

    def test_load_6h_preset(self):
        config = load_preset(DEFAULT_PRESET)
        assert config.race_duration_hours == 6.0
        assert len(config.drivers) == 3
        assert config.fuel_tank_liters == 100.0

    def test_default_preset_produces_feasible_plan(self):
        config = load_preset(DEFAULT_PRESET)
        plan = compute_plan(config)
        assert plan.is_feasible
        assert len(plan.stints) > 0
        assert plan.total_pit_stops >= 0


class TestFuelLimitedPlan:
    def test_fuel_limited_stint_geometry(self):
        config = _base_config(tyre_life_laps=80)
        plan = compute_plan(config)
        assert plan.is_feasible
        fuel_laps = fuel_limited_laps(config)
        assert fuel_laps > 0
        for stint in plan.stints[:-1]:
            assert stint.laps <= fuel_laps + 1


class TestTyreLimitedPlan:
    def test_tyre_limited_shorter_stints(self):
        fuel_cfg = _base_config(tyre_life_laps=80)
        tyre_cfg = _base_config(tyre_life_laps=10)
        fuel_plan = compute_plan(fuel_cfg)
        tyre_plan = compute_plan(tyre_cfg)
        assert fuel_plan.is_feasible
        assert tyre_plan.is_feasible
        assert len(tyre_plan.stints) >= len(fuel_plan.stints)
        assert any(s.limiting_factor == "Tyre-limited" for s in tyre_plan.stints)


class TestDriverRegulations:
    def test_max_continuous_stint_respected(self):
        config = _base_config()
        config.regulations.bronze_max_continuous_stint_min = 65.0
        plan = compute_plan(config)
        assert plan.is_feasible
        for stint in plan.stints:
            cap = config.regulations.max_stint_for_category(stint.driver.category)
            assert stint.duration_min <= cap + 1.0

    def test_bronze_minimum_satisfied_on_default_preset(self):
        config = load_preset(DEFAULT_PRESET)
        plan = compute_plan(config)
        assert plan.is_feasible
        totals = plan.driver_totals()
        bronze = next(d for d in config.drivers if d.category == DriverCategory.BRONZE)
        assert totals[bronze.name] >= config.regulations.bronze_min_drive_min - 1.0

    def test_bronze_minimum_violation_detected(self):
        config = _base_config(race_duration_hours=3.0)
        config.regulations.bronze_min_drive_min = 180.0
        plan = compute_plan(config)
        assert not plan.is_feasible
        messages = " ".join(i.message for i in plan.infeasibilities)
        assert "Bronze" in messages or "minimum" in messages.lower()


class TestInfeasibilityHandling:
    def test_infeasible_returns_reasons_not_exception(self):
        config = _base_config(
            fuel_tank_liters=1.0,
            fuel_consumption_per_lap=5.0,
        )
        plan = compute_plan(config)
        assert not plan.is_feasible
        assert len(plan.infeasibilities) > 0

    def test_zero_consumption_guarded(self):
        config = _base_config(fuel_consumption_per_lap=0.0)
        issues = validate_config(config)
        assert any(i.code == "invalid_consumption" for i in issues)

    def test_negative_duration_guarded(self):
        config = _base_config(race_duration_hours=-1.0)
        issues = validate_config(config)
        assert any(i.code == "invalid_race_duration" for i in issues)

    def test_no_drivers_infeasible(self):
        config = _base_config(drivers=[])
        plan = compute_plan(config)
        assert not plan.is_feasible


class TestSafetyCarReplan:
    def test_sc_replan_produces_comparison(self):
        config = load_preset(DEFAULT_PRESET)
        original = compute_plan(config)
        assert original.is_feasible
        sc = SafetyCarConfig(
            deploy_min=120.0,
            duration_min=15.0,
            lap_time_multiplier=1.4,
            sc_pit_loss_sec=25.0,
        )
        comparison = replan_with_safety_car(original, sc)
        assert comparison.replanned is not None
        assert len(comparison.replanned.stints) > 0
        assert comparison.notes

    def test_sc_at_race_end_handled(self):
        config = load_preset(DEFAULT_PRESET)
        original = compute_plan(config)
        sc = SafetyCarConfig(
            deploy_min=config.race_duration_min,
            duration_min=10.0,
        )
        comparison = replan_with_safety_car(original, sc)
        assert "end" in " ".join(comparison.notes).lower() or comparison.replanned.stints


class TestEdgeCases:
    def test_single_driver_plan(self):
        config = _base_config(
            drivers=[Driver("Solo", DriverCategory.PRO, 0.0)],
        )
        config.regulations.bronze_min_drive_min = 0.0
        plan = compute_plan(config)
        assert plan.is_feasible
        assert all(s.driver.name == "Solo" for s in plan.stints)

    def test_short_race_handled(self):
        config = _base_config(race_duration_hours=0.25)
        plan = compute_plan(config)
        assert plan.stints or plan.infeasibilities

    def test_tyre_life_override(self):
        config = load_preset(DEFAULT_PRESET)
        plan = compute_plan_with_tyre_life(config, 15)
        assert plan.is_feasible or plan.infeasibilities


class TestPresetFiles:
    def test_all_preset_json_valid(self):
        for path in PRESETS_DIR.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            config = RaceConfig.from_dict(data)
            plan = compute_plan(config)
            assert isinstance(plan.stints, list)