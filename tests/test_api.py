"""HTTP tests for the local API. Historical calls use an in-memory source."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.f1 import CarSpec, CompoundSpec, DriverSpec, F1Setup, TeamSpec
from engine.planner import DEFAULT_PRESET, PlanOptions, compute_plan, load_preset
from engine.safety_car import SafetyCarConfig, replan_with_safety_car
from engine.series_config import IMAGE_POLICY, setup_to_dict
from engine.strategy import compare_strategies
from historical.errors import HistoricalSourceError
from pitwall import __version__
from pitwall_api.app import create_app
from pitwall_api.schemas import PrepareRequest
from pitwall_api.service import RequestError, prepare_event

HEADSHOT = (
    "https://media.formula1.com/d_driver_fallback_image.png/content/dam/"
    "fom-website/drivers/M/MAXVER01_Max_Verstappen/maxver01.png.transform/1col/image.png"
)


def _toy() -> dict:
    setup = F1Setup(
        season=2024,
        round=1,
        event_name="Toy",
        race_laps=10,
        dry_race=True,
        time_limit_sec=2000,
        pit_lane_loss_sec=20.0,
        base_lap_time_sec=100.0,
        refuelling_allowed=False,
        dry_min_compounds=2,
        wet_min_compounds=1,
        max_stops=2,
        compounds=[
            CompoundSpec("SOFT", "Soft", True, "FF1E00", 4, -1.0, 0.0),
            CompoundSpec("HARD", "Hard", True, "F0F0F0", 10, 0.0, 0.0),
        ],
        cars=[
            CarSpec(
                "car",
                fuel_capacity_kg=20.0,
                fuel_consumption_kg_per_lap=1.5,
                starting_fuel_kg=20.0,
            )
        ],
        drivers=[
            DriverSpec(
                "VER",
                1,
                "Max VERSTAPPEN",
                team_name="Red Bull Racing",
                team_colour="3671c6",
                headshot_url=HEADSHOT,
                country_code="NED",
            )
        ],
        teams=[TeamSpec("Red Bull Racing", "3671c6", None)],
        data_source="Toy assumptions.",
        evidence_level="C",
    )
    return setup_to_dict(setup)


class FixtureSource:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[int, int]] = []

    def fetch_entry_list(self, season: int, round_: int):
        self.calls.append((season, round_))
        if self.fail:
            raise HistoricalSourceError("historical source unavailable")
        from tests.test_series_config import _entry

        return _entry()


def _client(source: object | None = None) -> TestClient:
    return TestClient(create_app(source if source is not None else FixtureSource()))


def test_health_reports_the_package_version() -> None:
    response = _client().get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "engine": "pitwall",
        "version": __version__,
    }
    assert __version__ == "0.4.0a2"


def test_f1_plan_returns_the_toy_strategy_and_driver_card() -> None:
    response = _client().post("/v1/plans", json={"series": "f1", "setup": _toy()})
    body = response.json()

    assert response.status_code == 200
    assert body["feasible"] is True
    assert body["race_time_sec"] == 1016.0
    assert body["stop_laps"] == [6]
    assert body["stints"][0]["compound"] == "HARD"
    assert body["stints"][0]["laps"] == 6
    assert body["stints"][1]["compound"] == "SOFT"
    assert body["stints"][1]["laps"] == 4
    assert body["candidates_checked"] == 8
    assert body["summary"].startswith("One pit stop.")
    assert body["uncertainty"].startswith("Not estimated.")
    assert body["drivers"][0]["headshot_url"] == HEADSHOT
    assert body["drivers"][0]["team_colour"] == "3671c6"
    assert body["drivers"][0]["team_colour_css"] == "#3671c6"
    assert body["teams"][0]["livery_image_url"] is None
    assert body["image_policy"] == IMAGE_POLICY
    assert "pre-race" in body["disclaimer"].lower() or body["disclaimer"]


def test_plain_detail_keeps_the_answer_and_drops_provenance() -> None:
    response = _client().post(
        "/v1/plans",
        json={"series": "f1", "setup": _toy(), "detail": "plain"},
    )
    body = response.json()

    assert body["race_time_sec"] == 1016.0
    assert body["summary"]
    assert body["rules"]
    assert body["assumptions"]
    assert body["provenance"] is None
    assert body["candidates_checked"] is None


def test_f1_safety_car_savings_match_the_engine() -> None:
    client = _client()
    pulled = client.post(
        "/v1/safety-car",
        json={
            "series": "f1",
            "setup": _toy(),
            "safety_car": {
                "start_lap": 7,
                "end_lap": 8,
                "pit_loss_sec": 8,
                "pull_pit_into_sc": True,
            },
        },
    ).json()
    held = client.post(
        "/v1/safety-car",
        json={
            "series": "f1",
            "setup": _toy(),
            "safety_car": {
                "start_lap": 6,
                "end_lap": 8,
                "pit_loss_sec": 8,
                "pull_pit_into_sc": False,
            },
        },
    ).json()

    assert pulled["time_saved_sec"] == 11.0
    assert pulled["stops_moved"] is True
    assert pulled["stop_laps"] == [7]
    assert "not resimulated" in pulled["confidence"]
    assert held["time_saved_sec"] == 12.0
    assert held["stops_moved"] is False
    assert held["stop_laps"] == [6]
    assert "saving 12.000 s" in held["summary"]


def test_f1_compare_ranks_the_slower_named_plan() -> None:
    response = _client().post(
        "/v1/scenarios/compare",
        json={
            "series": "f1",
            "setup": _toy(),
            "scenarios": [
                {
                    "name": "Short soft",
                    "stints": [
                        {"compound": "SOFT", "laps": 2},
                        {"compound": "HARD", "laps": 8},
                    ],
                }
            ],
        },
    )
    body = response.json()
    names = [row["strategy_name"] for row in body["scenarios"]]

    assert names[0] == "Suggested"
    assert body["scenarios"][0]["race_time_sec"] == 1016.0
    assert body["scenarios"][1]["strategy_name"] == "Short soft"
    assert body["scenarios"][1]["race_time_sec"] == 1018.0
    assert body["scenarios"][1]["ranking_reason"] == (
        "Slower than the leading legal plan by 2.000 s."
    )


def test_prepare_offline_skips_the_source_and_refresh_fills_the_card() -> None:
    source = FixtureSource()
    client = _client(source)
    offline = client.post("/v1/f1/events/2024/1/prepare", json={"offline": True}).json()

    assert source.calls == []
    assert offline["ready_to_plan"] is True
    assert offline["drivers"] == []
    assert any("not refreshed" in note for note in offline["assumptions"])

    refreshed = client.post(
        "/v1/f1/events/2024/1/prepare",
        json={
            "overrides": {
                "drivers": [{"code": "VER", "pace_delta_sec": -0.2}],
                "base_lap_time_sec": 95.529,
            }
        },
    ).json()

    assert source.calls == [(2024, 1)]
    assert refreshed["ready_to_plan"] is True
    assert refreshed["drivers"][0]["headshot_url"] == HEADSHOT
    assert refreshed["drivers"][0]["team_colour_css"] == "#3671c6"
    assert refreshed["drivers"][0]["pace_delta_sec"] == -0.2
    assert refreshed["provenance"]["drivers.VER.headshot_url"] == "fetched"
    assert refreshed["provenance"]["drivers.VER.pace_delta_sec"] == "user"
    assert refreshed["provenance"]["base_lap_time_sec"] == "user"
    assert refreshed["teams"][0]["livery_image_url"] is None


def test_event_file_view_and_missing_round() -> None:
    client = _client()
    found = client.get("/v1/f1/events/2024/1")
    template = client.get("/v1/f1/events/1999/1")

    assert found.status_code == 200
    assert found.json()["race_laps"] == 57
    assert template.status_code == 200
    assert template.json()["race_laps"] is None
    assert template.json()["provenance"]["refuelling_allowed"] == "season-template-2025"


def test_backtest_endpoint_returns_the_bahrain_literals() -> None:
    response = _client().post("/v1/backtests/2024-r01-bahrain-verstappen")
    body = response.json()

    assert response.status_code == 200
    assert body["predicted_race_time_sec"] == 5496.363
    assert body["actual_race_time_sec"] == 5504.742
    assert body["race_time_delta_sec"] == -8.379
    assert body["replay_race_time_sec"] == 5504.713
    assert body["replay_time_delta_sec"] == -0.029
    assert body["predicted_stint_laps"] == [35, 22]
    assert body["actual_stop_laps"] == [17, 37]
    assert body["same_stop_count"] is False
    assert body["team_colour_css"] == "#3671c6"
    assert body["livery_image_url"] is None
    assert any(note.startswith("Predicted 1 stop (") for note in body["notes"])


def test_unknown_fixture_is_404_and_a_source_failure_is_502() -> None:
    client = _client(FixtureSource(fail=True))

    missing = client.post("/v1/backtests/not-a-real-fixture")
    failed = client.post("/v1/f1/events/2024/1/prepare", json={})
    bare = client.post("/v1/plans", json={"series": "f1"})
    endurance = client.post("/v1/plans", json={"series": "endurance"})
    bad_window = client.post(
        "/v1/safety-car",
        json={"series": "f1", "setup": _toy(), "safety_car": {"start_lap": 1}},
    )

    assert missing.status_code == 404
    assert failed.status_code == 502
    assert "unavailable" in failed.json()["detail"]
    assert bare.status_code == 400
    assert endurance.status_code == 400
    assert bad_window.status_code == 400


def test_endurance_compare_and_safety_car_match_the_engine() -> None:
    config = load_preset(DEFAULT_PRESET)
    race = config.to_dict()
    comparison = compare_strategies(config)
    original = compute_plan(config, PlanOptions())
    scenario = SafetyCarConfig(deploy_min=120.0, duration_min=20.0)
    replanned = replan_with_safety_car(original, scenario)
    client = _client()

    compared = client.post(
        "/v1/scenarios/compare",
        json={"series": "endurance", "race": race},
    ).json()
    safety = client.post(
        "/v1/safety-car",
        json={
            "series": "endurance",
            "race": race,
            "safety_car": {"deploy_min": 120, "duration_min": 20},
        },
    ).json()
    single = client.post("/v1/plans", json={"series": "endurance", "race": race}).json()

    assert len(compared["scenarios"]) == len(comparison.outcomes)
    for row, outcome in zip(compared["scenarios"], comparison.outcomes, strict=True):
        assert row["simulation"]["laps_p10"] == outcome.simulation.laps_p10
        assert row["simulation"]["laps_median"] == outcome.simulation.laps_median
        assert row["simulation"]["laps_p90"] == outcome.simulation.laps_p90
        assert row["rank"] == outcome.rank
    assert safety["time_delta_min"] == replanned.time_delta_min
    assert "P10–P90" in single["uncertainty"] or "P10" in single["uncertainty"]
    assert single["predicted_laps"] == original.predicted_laps


def test_prepare_without_a_source_is_a_request_error() -> None:
    with pytest.raises(RequestError, match="No historical source"):
        prepare_event(2024, 1, PrepareRequest(), None)


def test_named_stints_and_season_round_plans() -> None:
    client = _client()
    custom = client.post(
        "/v1/plans",
        json={
            "series": "f1",
            "setup": _toy(),
            "strategy": [
                {"compound": "HARD", "laps": 6},
                {"compound": "SOFT", "laps": 4},
            ],
        },
    ).json()
    bundled = client.post(
        "/v1/plans", json={"series": "f1", "season": 2024, "round": 1}
    ).json()

    assert custom["strategy_name"] == "Custom"
    assert custom["race_time_sec"] == 1016.0
    assert custom["stop_laps"] == [6]
    assert bundled["feasible"] is True
    assert bundled["predicted_laps"] == 57
    assert bundled["provenance"]["pit_lane_loss_sec"] == "event"


def test_bad_inputs_are_400_and_an_illegal_endurance_plan_stays_honest() -> None:
    client = _client()
    race = load_preset(DEFAULT_PRESET).to_dict()
    race["drivers"] = []
    bad_race = client.post(
        "/v1/plans", json={"series": "endurance", "race": {"race_name": 1}}
    )
    bad_window = client.post(
        "/v1/safety-car",
        json={"series": "endurance", "race": race, "safety_car": {}},
    )
    bad_override = client.post(
        "/v1/f1/events/2024/1/prepare",
        json={"offline": True, "overrides": {"pit_lane_loss_sec": "slow"}},
    )
    illegal = client.post(
        "/v1/plans", json={"series": "endurance", "race": race}
    ).json()

    assert bad_race.status_code == 400
    assert bad_window.status_code == 400
    assert "deploy_min" in bad_window.json()["detail"]
    assert bad_override.status_code == 400
    assert illegal["feasible"] is False
    assert illegal["summary"].startswith("This setup cannot make a legal plan.")


def test_endurance_safety_car_deploy_outside_the_race_is_422() -> None:
    client = _client()
    config = load_preset(DEFAULT_PRESET)
    race = config.to_dict()
    late = client.post(
        "/v1/safety-car",
        json={
            "series": "endurance",
            "race": race,
            "safety_car": {
                "deploy_min": config.race_duration_min + 1,
                "duration_min": 5,
            },
        },
    )
    negative = client.post(
        "/v1/safety-car",
        json={
            "series": "endurance",
            "race": race,
            "safety_car": {"deploy_min": -1, "duration_min": 5},
        },
    )

    assert late.status_code == 422
    assert "deploy_min" in late.json()["detail"]
    assert "past the race" in late.json()["detail"]
    assert negative.status_code == 422
    assert "past the race" not in negative.json()["detail"]
    assert "zero or higher" in negative.json()["detail"]


def test_event_round_outside_1_to_30_is_422() -> None:
    client = _client()
    low = client.get("/v1/f1/events/2024/0")
    high = client.get("/v1/f1/events/2024/31")
    prepare_low = client.post("/v1/f1/events/2024/0/prepare", json={"offline": True})
    prepare_high = client.post("/v1/f1/events/2024/31/prepare", json={"offline": True})
    ok = client.get("/v1/f1/events/2024/1")

    assert low.status_code == 422
    assert high.status_code == 422
    assert prepare_low.status_code == 422
    assert prepare_high.status_code == 422
    assert ok.status_code == 200


def test_request_bounds_reject_a_bad_stint_season_and_too_many_scenarios() -> None:
    client = _client()
    short = client.post(
        "/v1/plans",
        json={
            "series": "f1",
            "setup": _toy(),
            "strategy": [{"compound": "HARD", "laps": 0}],
        },
    )
    season = client.post(
        "/v1/plans",
        json={"series": "f1", "season": 1800, "round": 1},
    )
    scenarios = client.post(
        "/v1/scenarios/compare",
        json={
            "series": "f1",
            "setup": _toy(),
            "scenarios": [{"name": f"S{index}", "stints": None} for index in range(9)],
        },
    )

    assert short.status_code == 422
    assert season.status_code == 422
    assert scenarios.status_code == 422


def test_api_entrypoint_stays_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall_api.__main__ import main

    seen: dict[str, object] = {}

    def run(target: str, host: str, port: int) -> None:
        seen["target"] = target
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr("uvicorn.run", run)
    main([])

    assert seen == {"target": "pitwall_api.app:app", "host": "127.0.0.1", "port": 8000}


def test_event_route_turns_a_bad_file_into_400(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(season: int, round_: int) -> None:
        raise ValueError(f"bad file for {season} round {round_}")

    monkeypatch.setattr("pitwall_api.app.load_setup", boom)
    response = _client().get("/v1/f1/events/2024/1")

    assert response.status_code == 400
    assert response.json()["detail"] == "bad file for 2024 round 1"
