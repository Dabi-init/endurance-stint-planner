"""Runtime hardening tests — helpers + lightweight UI smoke passes."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CRASH_MSG = "Something went wrong"


def _assert_no_crash(at) -> None:
    assert not at.exception, [str(e.value) for e in at.exception]
    crash_errors = [
        e.value for e in at.error
        if e.value and CRASH_MSG in e.value
    ]
    assert not crash_errors, crash_errors


def _fresh_app():
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


class TestAppHelpers:
    def test_empty_cache_returns_infeasible_not_exception(self):
        import app

        plan = app._cache_to_plan({})
        assert not plan.is_feasible
        assert plan.infeasibilities

    def test_corrupt_cache_still_parses(self):
        import app

        plan = app._cache_to_plan({
            "config": {},
            "stints_raw": [{"driver_name": "X", "bad": True}],
            "total_pit_stops": "nope",
        })
        assert plan.total_pit_stops == 0

    def test_driver_category_index_fallback(self):
        import app

        assert app._driver_category_index("Pro") == 0
        assert app._driver_category_index("NotARealCategory") == 0

    def test_clamp_tyre_life_bounds(self):
        import app

        assert app._clamp_tyre_life(3) == 5
        assert app._clamp_tyre_life(99) == 80
        assert app._clamp_tyre_life(28) == 28

    def test_all_presets_render_charts(self):
        import app
        from engine.circuits import DEFAULT_CIRCUIT_ID, apply_circuit_to_config, get_circuit
        from engine.models import RaceConfig
        from engine.planner import list_presets, load_preset, compute_plan

        circuit = get_circuit(DEFAULT_CIRCUIT_ID)
        for preset in list_presets():
            cfg = apply_circuit_to_config(load_preset(preset).to_dict(), circuit)
            plan = compute_plan(RaceConfig.from_dict(cfg))
            cached = app._plan_to_cache(plan)
            restored = app._cache_to_plan(cached)
            app._build_timeline_figure(restored, preset)
            app._driver_compliance_chart(restored)
            app._tyre_strategy_chart(restored, cfg["tyre_life_laps"])

    def test_all_circuits_render_charts(self):
        import app
        from engine.circuits import (
            apply_circuit_to_config,
            circuit_id_from_display,
            get_circuit,
            list_circuit_names,
        )
        from engine.models import RaceConfig
        from engine.planner import DEFAULT_PRESET, compute_plan, load_preset

        base = load_preset(DEFAULT_PRESET).to_dict()
        for name in list_circuit_names():
            cid = circuit_id_from_display(name)
            cfg = apply_circuit_to_config(base, get_circuit(cid))
            plan = compute_plan(RaceConfig.from_dict(cfg))
            app._build_timeline_figure(plan, name)
            app._tyre_strategy_chart(plan, app._clamp_tyre_life(cfg["tyre_life_laps"]))


class TestAppUiSmoke:
    def test_default_load_no_crash(self):
        at = _fresh_app()
        at.run()
        _assert_no_crash(at)

    @pytest.mark.parametrize("preset", [
        "6h Endurance",
        "24h GT3 Endurance",
        "4h Sprint Endurance",
    ])
    def test_preset_switch_no_crash(self, preset: str):
        at = _fresh_app()
        at.run()
        at.sidebar.selectbox[0].set_value(preset).run()
        _assert_no_crash(at)

    def test_recompute_button_no_crash(self):
        at = _fresh_app()
        at.run()
        at.sidebar.button[0].click().run()
        _assert_no_crash(at)

    def test_safety_car_button_no_crash(self):
        at = _fresh_app()
        at.run()
        for btn in at.button:
            if btn.label == "Replan with Safety Car":
                btn.click().run()
                break
        _assert_no_crash(at)

    def test_high_tyre_life_no_crash(self):
        at = _fresh_app()
        at.run()
        for ni in at.sidebar.number_input:
            if ni.label and "Tyre life" in ni.label:
                ni.set_value(80).run()
                break
        _assert_no_crash(at)