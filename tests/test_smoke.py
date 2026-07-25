"""High-value smoke tests for a fresh local clone."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pitwall.cli import app

ROOT = Path(__file__).resolve().parent.parent
RUNNER = CliRunner()


class TestProjectStructure:
    def test_required_product_files_exist(self) -> None:
        required = [
            "pitwall/cli.py",
            "pitwall/agent.py",
            "pitwall/tools.py",
            "pitwall/providers.py",
            "engine/planner.py",
            "engine/strategy.py",
            "engine/simulation.py",
            "engine/telemetry.py",
            "examples/spa_6h_synthetic.csv",
            "docs/AGENT_BRAIN.md",
            "pyproject.toml",
        ]
        for relative_path in required:
            assert (ROOT / relative_path).exists(), f"Missing: {relative_path}"


class TestDefaultUserJourney:
    def test_synthetic_example_produces_decision_ready_comparison(self) -> None:
        from engine.planner import DEFAULT_PRESET, load_preset
        from engine.strategy import compare_strategies
        from engine.telemetry import calibrate_telemetry

        sample = ROOT / "examples" / "spa_6h_synthetic.csv"
        calibration = calibrate_telemetry(
            sample.read_bytes(),
            source_name=sample.name,
            is_synthetic=True,
        )
        config = load_preset(DEFAULT_PRESET)
        for key, value in calibration.config_patch().items():
            setattr(config, key, value)
        config.data_source = calibration.source_label
        comparison = compare_strategies(config, calibration, iterations=30)

        assert comparison.preferred.plan.is_feasible
        assert len(comparison.outcomes) == 3
        assert comparison.preferred.plan.stints
        assert calibration.evidence_level == "C"

    def test_module_and_console_version(self) -> None:
        import pitwall

        result = RUNNER.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert pitwall.__version__ in result.stdout

    def test_doctor_and_compare_work_without_an_ai_model(self, tmp_path: Path) -> None:
        home = tmp_path / ".pitwall"
        doctor = RUNNER.invoke(app, ["--home", str(home), "doctor"])
        comparison = RUNNER.invoke(app, ["--home", str(home), "compare"])

        assert doctor.exit_code == 0, doctor.stdout
        assert "strategy core" in doctor.stdout
        assert comparison.exit_code == 0, comparison.stdout
        assert "Recommendation" in comparison.stdout

    def test_engine_never_raises_on_bad_input(self) -> None:
        from engine.models import RaceConfig
        from engine.planner import compute_plan

        plan = compute_plan(
            RaceConfig.from_dict(
                {
                    "race_name": "Bad",
                    "race_duration_hours": -1,
                    "base_lap_time_sec": 0,
                    "fuel_tank_liters": 0,
                    "fuel_consumption_per_lap": 0,
                    "pit_stop_time_loss_sec": -1,
                    "refuel_rate_liters_per_sec": 0,
                    "tyre_life_laps": 0,
                    "tyre_change_time_sec": 0,
                    "drivers": [],
                }
            )
        )
        assert not plan.is_feasible
        assert plan.infeasibilities
