"""Declared weather, exclusive sheets, the back-test panel, and source terms."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.f1 import best_f1_plan
from engine.series_config import apply_overrides, load_setup
from historical.terms import JOLPICA_TERMS, OPENF1_TERMS
from pitwall_api.app import create_app
from pitwall_api.schemas import SheetRequest
from pitwall_api.service import COMMERCIAL_NOTE, save_sheet


def _client() -> TestClient:
    return TestClient(create_app(object()))


def test_declared_weather_is_not_a_forecast() -> None:
    client = _client()
    dry = client.post(
        "/v1/f1/weather",
        json={"season": 2024, "round": 1, "declared": "dry"},
    )
    wet = client.post(
        "/v1/f1/weather",
        json={"season": 2024, "round": 1, "declared": "wet"},
    )
    assumed = client.post(
        "/v1/f1/weather",
        json={"season": 2024, "round": 1, "declared": "wet", "wet_life_laps": 30},
    )

    assert dry.status_code == 200
    assert dry.json()["forecast"] is False
    assert dry.json()["open_meteo"] == "not called"
    assert dry.json()["plan"]["race_time_sec"] == 5466.21
    assert "Open-Meteo is not called" in dry.json()["note"]
    assert wet.json()["plan"]["feasible"] is False
    assert "stint life" in wet.json()["note"]
    setup = apply_overrides(
        load_setup(2024, 1),
        {
            "dry_race": False,
            "compounds": {
                "INTERMEDIATE": {"max_laps": 30},
                "WET": {"max_laps": 30},
            },
        },
    )
    expected = best_f1_plan(setup)
    body = assumed.json()
    assert body["plan"]["feasible"] is True
    assert body["plan"]["race_time_sec"] == expected.race_time_sec
    assert "30 laps you typed" in body["note"]
    assert body["forecast"] is False


def test_sheets_are_created_once_and_never_replace_race_json(tmp_path: Path) -> None:
    first = save_sheet(
        SheetRequest(name="bahrain plan", document={"series": "f1", "laps": 57}),
        root=tmp_path,
    )
    written = tmp_path / first.name
    original = written.read_text(encoding="utf-8")

    with pytest.raises(Exception, match="already exists") as blocked:
        save_sheet(
            SheetRequest(name="bahrain plan", document={"series": "f1", "laps": 1}),
            root=tmp_path,
        )
    with pytest.raises(Exception, match=r"race\.json"):
        save_sheet(
            SheetRequest(name="race.json", document={"race": True}), root=tmp_path
        )
    with pytest.raises(Exception, match=r"race\.json"):
        save_sheet(
            SheetRequest(name="../race.json", document={"race": True}), root=tmp_path
        )

    assert first.created is True
    assert first.name == "bahrain-plan.json"
    assert written.read_text(encoding="utf-8") == original
    assert "Nothing was overwritten" in str(blocked.value)
    assert not (tmp_path / "race.json").exists()


def test_sheet_and_terms_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pitwall_api.service.SHEET_DIR", tmp_path)
    client = _client()
    created = client.post(
        "/v1/sheets",
        json={"name": "sheet-a", "document": {"label": "Bahrain"}},
    )
    again = client.post(
        "/v1/sheets",
        json={"name": "sheet-a", "document": {"label": "changed"}},
    )
    race = client.post("/v1/sheets", json={"name": "race.json", "document": {}})
    terms = client.get("/v1/terms")

    assert created.status_code == 200
    assert created.json()["created"] is True
    assert "race.json was not written" in created.json()["note"]
    assert again.status_code == 409
    assert race.status_code == 400
    assert (tmp_path / "sheet-a.json").is_file()
    assert not (tmp_path / "race.json").exists()
    assert terms.json()["openf1"] == OPENF1_TERMS
    assert terms.json()["jolpica"] == JOLPICA_TERMS
    assert terms.json()["commercial"] == COMMERCIAL_NOTE
    assert "non-commercial" in terms.json()["openf1"]
