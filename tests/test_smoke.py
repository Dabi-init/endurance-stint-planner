"""Smoke tests — verify the full stack loads and produces a default plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestProjectStructure:
    def test_required_files_exist(self):
        required = [
            "app.py",
            "requirements.txt",
            "engine/planner.py",
            "engine/models.py",
            "presets/6h_endurance.json",
            "circuits/circuits.json",
            ".streamlit/config.toml",
        ]
        for rel in required:
            assert (ROOT / rel).exists(), f"Missing: {rel}"

    def test_circuits_json_valid(self):
        data = json.loads((ROOT / "circuits" / "circuits.json").read_text(encoding="utf-8"))
        assert len(data) >= 6
        for circuit in data:
            assert "id" in circuit
            assert "tyre_wear" in circuit


class TestDefaultUserJourney:
    """Simulates race engineer opening the app before a race weekend."""

    def test_zero_input_feasible_plan(self):
        from engine.circuits import DEFAULT_CIRCUIT_ID, apply_circuit_to_config, get_circuit
        from engine.models import DriverCategory, RaceConfig
        from engine.planner import DEFAULT_PRESET, compute_plan, load_preset
        from engine.recommendations import generate_strategy_report

        cfg = apply_circuit_to_config(
            load_preset(DEFAULT_PRESET).to_dict(),
            get_circuit(DEFAULT_CIRCUIT_ID),
        )
        plan = compute_plan(RaceConfig.from_dict(cfg))

        assert plan.is_feasible, [i.message for i in plan.infeasibilities]
        assert len(plan.stints) >= 5
        assert plan.total_pit_stops >= 1
        assert plan.predicted_laps > 0

        bronze = next(d for d in plan.config.drivers if d.category == DriverCategory.BRONZE)
        assert plan.driver_totals()[bronze.name] >= 120.0 - 1.0

        report = generate_strategy_report(plan, DEFAULT_CIRCUIT_ID)
        assert report.insights
        assert report.metrics.avg_stint_laps > 0

    def test_app_module_imports(self):
        import app
        assert app.APP_VERSION
        assert app.DEFAULT_PRESET == "6h Endurance"

    def test_app_loads_without_runtime_error(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        error_texts = [e.value for e in at.error]
        assert not any(
            "Something went wrong" in t for t in error_texts
        ), error_texts

    def test_engine_never_raises_on_bad_input(self):
        from engine.models import RaceConfig
        from engine.planner import compute_plan

        plan = compute_plan(
            RaceConfig.from_dict({
                "race_name": "Bad",
                "race_duration_hours": -1,
                "base_lap_time_sec": 0,
                "fuel_tank_liters": 0,
                "fuel_consumption_per_lap": 0,
                "pit_stop_time_loss_sec": 55,
                "refuel_rate_liters_per_sec": 0,
                "tyre_life_laps": 0,
                "tyre_change_time_sec": 0,
                "drivers": [],
            })
        )
        assert not plan.is_feasible
        assert plan.infeasibilities