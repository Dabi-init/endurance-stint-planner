"""Tests for circuit profiles and strategy recommendations."""

from __future__ import annotations

from engine.circuits import (
    DEFAULT_CIRCUIT_ID,
    apply_circuit_to_config,
    get_circuit,
    load_circuits,
    recommended_stint_laps,
)
from engine.planner import compute_plan, load_preset, DEFAULT_PRESET
from engine.recommendations import generate_strategy_report


class TestCircuits:
    def test_load_six_circuits(self):
        circuits = load_circuits()
        assert len(circuits) >= 6

    def test_high_wear_shortens_tyres_vs_low_wear(self):
        spa = get_circuit("spa-francorchamps")
        monza = get_circuit("monza")
        assert spa.tyre_wear == "High"
        assert monza.tyre_wear == "Low"
        base = load_preset(DEFAULT_PRESET).to_dict()
        spa_cfg = apply_circuit_to_config(base, spa)
        monza_cfg = apply_circuit_to_config(base, monza)
        assert spa_cfg["tyre_life_laps"] < monza_cfg["tyre_life_laps"]

    def test_apply_circuit_updates_lap_time_and_fuel(self):
        circuit = get_circuit(DEFAULT_CIRCUIT_ID)
        base = load_preset(DEFAULT_PRESET).to_dict()
        updated = apply_circuit_to_config(base, circuit)
        assert updated["base_lap_time_sec"] == circuit.base_lap_time_sec
        assert updated["fuel_consumption_per_lap"] == circuit.fuel_consumption_per_lap
        assert updated["circuit_id"] == circuit.id

    def test_circuit_plan_remains_feasible(self):
        config = load_preset(DEFAULT_PRESET)
        circuit = get_circuit("nurburgring-gp")
        cfg_dict = apply_circuit_to_config(config.to_dict(), circuit)
        from engine.models import RaceConfig
        plan = compute_plan(RaceConfig.from_dict(cfg_dict))
        assert plan.is_feasible

    def test_recommended_stint_geometry(self):
        circuit = get_circuit("portimao")
        cfg = apply_circuit_to_config(load_preset(DEFAULT_PRESET).to_dict(), circuit)
        geom = recommended_stint_laps(cfg, circuit)
        assert geom["fuel_laps"] > 0
        assert geom["tyre_laps"] > 0
        assert geom["recommended_laps"] > 0


class TestRecommendations:
    def test_generates_insights_for_default_plan(self):
        config = load_preset(DEFAULT_PRESET)
        cfg_dict = apply_circuit_to_config(
            config.to_dict(), get_circuit(DEFAULT_CIRCUIT_ID)
        )
        from engine.models import RaceConfig
        plan = compute_plan(RaceConfig.from_dict(cfg_dict))
        report = generate_strategy_report(plan, DEFAULT_CIRCUIT_ID)
        assert report.circuit is not None
        assert report.metrics.avg_stint_laps > 0
        assert len(report.insights) > 0
        assert report.race_approach_summary

    def test_high_sc_risk_circuit_notes_sc(self):
        config = load_preset(DEFAULT_PRESET)
        fuji = get_circuit("fuji")
        cfg_dict = apply_circuit_to_config(config.to_dict(), fuji)
        from engine.models import RaceConfig
        plan = compute_plan(RaceConfig.from_dict(cfg_dict))
        report = generate_strategy_report(plan, fuji.id)
        sc_insights = [i for i in report.insights if i.category == "Safety Car"]
        assert any("SC" in i.title or "SC" in i.detail for i in sc_insights)

    def test_infeasible_plan_summary(self):
        from engine.models import RaceConfig
        config = load_preset(DEFAULT_PRESET)
        config.regulations.bronze_min_drive_min = 9999.0
        plan = compute_plan(config)
        report = generate_strategy_report(plan)
        assert "infeasibility" in report.race_approach_summary.lower()