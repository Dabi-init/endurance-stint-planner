"""Endurance on the pit wall uses bundled presets and refuses remote timing."""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.planner import DEFAULT_PRESET, compute_plan, list_presets, load_preset
from engine.telemetry import calibrate_telemetry
from pitwall_api.app import create_app
from pitwall_api.service import TIMING_REFUSAL


def _client() -> TestClient:
    return TestClient(create_app(object()))


def _sample_csv() -> str:
    rows = ["lap,driver,lap_time_sec,fuel_remaining_liters"]
    fuel = 100.0
    for lap in range(1, 13):
        rows.append(f"{lap},Alex Pro,{120 + lap * 0.2:.1f},{fuel:.1f}")
        fuel -= 3.0
    return "\n".join(rows) + "\n"


def test_presets_are_the_bundled_synthetic_files() -> None:
    client = _client()
    listed = client.get("/v1/endurance/presets")
    opened = client.get("/v1/endurance/preset", params={"name": DEFAULT_PRESET})
    missing = client.get("/v1/endurance/preset", params={"name": "Le Mans 2024"})

    assert listed.status_code == 200
    assert listed.json()["presets"] == list_presets()
    assert "Al Kamel" in listed.json()["note"]
    assert opened.status_code == 200
    body = opened.json()
    assert body["synthetic"] is True
    assert body["evidence_level"] == "C"
    assert body["race"]["race_name"] == load_preset(DEFAULT_PRESET).race_name
    assert {driver["category"] for driver in body["race"]["drivers"]} == {
        "Pro",
        "Silver",
        "Bronze",
    }
    assert missing.status_code == 404


def test_classes_are_separate_plans() -> None:
    client = _client()
    six = load_preset("6h Endurance")
    sprint = load_preset("4h Sprint Endurance")
    response = client.post(
        "/v1/endurance/classes",
        json={
            "classes": [
                {"name": "GT3", "race": six.to_dict()},
                {"name": "Sprint", "race": sprint.to_dict()},
            ]
        },
    )

    assert response.status_code == 200
    rows = response.json()["classes"]
    assert [row["name"] for row in rows] == ["GT3", "Sprint"]
    assert rows[0]["plan"]["predicted_laps"] == compute_plan(six).predicted_laps
    assert rows[0]["plan"]["predicted_laps"] == 174
    assert rows[1]["plan"]["predicted_laps"] == compute_plan(sprint).predicted_laps
    assert "not combined" in response.json()["note"]
    assert any(driver["team_name"] == "Silver" for driver in rows[0]["plan"]["drivers"])


def test_pasted_laps_calibrate_and_a_url_is_refused() -> None:
    client = _client()
    csv = _sample_csv()
    expected = calibrate_telemetry(csv, source_name="pasted.csv", is_synthetic=True)
    preview = client.post(
        "/v1/endurance/telemetry",
        json={"csv": csv, "synthetic": True},
    )
    link = client.post(
        "/v1/endurance/telemetry",
        json={"csv": "https://example.test/alkamel/session.csv", "synthetic": False},
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["synthetic"] is True
    assert body["usable_for_strategy"] is True
    assert body["calibration"]["median_lap_time_sec"] == expected.median_lap_time_sec
    assert body["config_patch"]["fuel_consumption_per_lap"] == 3.0
    assert link.status_code == 400
    assert link.json()["detail"] == TIMING_REFUSAL
    assert "example.test" not in link.json()["detail"]
