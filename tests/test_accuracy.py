"""Exact accuracy-log arithmetic. Network fixtures stand in for OpenF1 and FastF1."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accuracy.publish import build_log, read_log, render_page, write_log, write_page
from accuracy.score import NOTICE, recommend, score_race, season_rates
from accuracy.sources import collect_fastf1, fetch_openf1
from historical.errors import HistoricalSourceError
from pitwall_api.app import create_app

BASE = "https://api.openf1.org/v1"


def test_fifty_eight_lap_plan_is_one_stop_on_lap_36() -> None:
    plan = recommend(2026, 1, 58)

    assert plan["feasible"] is True
    assert plan["stop_laps"] == [36]
    assert plan["stint_laps"] == [36, 22]
    assert plan["compounds"] == ["HARD", "SOFT"]


def test_seventy_eight_lap_plan_is_two_stops() -> None:
    plan = recommend(2026, 6, 78)

    assert plan["feasible"] is True
    assert plan["stop_laps"] == [28, 56]
    assert plan["stint_laps"] == [28, 28, 22]
    assert plan["compounds"] == ["MEDIUM", "MEDIUM", "SOFT"]


def test_error_rates_use_the_published_definition() -> None:
    plan = {
        "feasible": True,
        "stop_laps": [18, 40],
        "stint_laps": [18, 22, 17],
        "compounds": ["MEDIUM", "HARD", "SOFT"],
        "message": "Two pit stops.",
    }
    race = score_race(
        {
            "round": 1,
            "event_name": "Sample Grand Prix",
            "race_date": "2026-03-08",
            "meeting_key": 1,
            "race_laps": 57,
            "source": "openf1",
            "wet_tyres_seen": False,
            "drivers": [
                _driver("A", 1, 1, 1, [20, 40], [20, 20, 17]),
                _driver("B", 2, 2, 3, [18, 40], [18, 22, 17]),
                _driver("C", 3, 3, 2, [18], [18, 39]),
                _driver("D", 4, None, 4, [10], [10]),
                _driver("E", 5, 4, None, [5], [5], classified=False, status="dnf"),
            ],
        },
        plan,
    )
    wet = score_race(
        {
            "round": 2,
            "event_name": "Wet Grand Prix",
            "race_date": "2026-03-15",
            "meeting_key": 2,
            "race_laps": 56,
            "source": "openf1",
            "wet_tyres_seen": True,
            "drivers": [_driver("F", 6, 1, 1, [1], [1, 55])],
        },
        plan,
    )
    rates = season_rates([race, wet])

    assert race["drivers"][0]["pit_lap_mae"] == 1.0
    assert race["drivers"][0]["stint_length_mae"] == 1.333
    assert race["drivers"][1]["pit_lap_mae"] == 0.0
    assert race["drivers"][2]["pit_lap_mae"] == 0.0
    assert race["drivers"][2]["stint_length_mae"] == 8.5
    assert race["drivers"][2]["stop_count_abs"] == 1
    assert race["drivers"][3]["pit_lap_mae"] == 8.0
    assert race["drivers"][4]["strategy_scored"] is False
    assert race["drivers"][4]["finish_scored"] is False
    assert [
        (pair["behind"], pair["predicted"], pair["actual"], pair["hit"])
        for pair in race["undercut_pairs"]
    ] == [
        ("B", False, True, False),
        ("C", False, False, True),
    ]
    assert race["rates"]["pit_lap_mae"] == 2.25
    assert race["rates"]["stint_length_mae"] == 4.458
    assert race["rates"]["stop_count_mae"] == 0.5
    assert race["rates"]["undercut_error_rate"] == 0.5
    assert race["rates"]["finish_order_mae"] == 0.667
    assert wet["strategy_scored"] is False
    assert wet["drivers"][0]["pit_lap_mae"] is None
    assert wet["drivers"][0]["finish_scored"] is True
    assert rates["pit_lap_mae"] == 2.25
    assert rates["stint_length_mae"] == 4.458
    assert rates["stop_count_mae"] == 0.5
    assert rates["undercut_error_rate"] == 0.5
    assert rates["finish_order_mae"] == 0.5
    assert rates["strategy_races"] == 1
    assert rates["races"] == 2
    assert rates["undercut_pairs"] == 2
    assert rates["undercut_hits"] == 1


def test_static_page_shows_exact_rates_and_the_notice(tmp_path: Path) -> None:
    plan = {
        "feasible": True,
        "stop_laps": [18, 40],
        "stint_laps": [18, 22, 17],
        "compounds": ["HARD", "SOFT"],
        "message": "Two pit stops.",
    }
    race = score_race(
        {
            "round": 1,
            "event_name": "A < B Grand Prix",
            "race_date": "2026-03-08",
            "meeting_key": None,
            "race_laps": 57,
            "source": "openf1",
            "wet_tyres_seen": False,
            "drivers": [
                _driver("A", 1, 1, 1, [20, 40], [20, 20, 17]),
                _driver("B", 2, 2, 3, [18, 40], [18, 22, 17]),
                _driver("C", 3, 3, 2, [18], [18, 39]),
                _driver("D", 4, None, 4, [10], [10]),
            ],
        },
        plan,
    )
    payload = {
        "season": 2026,
        "as_of": "2026-10-16",
        "notice": NOTICE,
        "honesty": "Not validated yet.",
        "assumption": "One pack.",
        "rates": season_rates([race]),
        "races": [race],
    }
    page = render_page(payload)
    path = write_page(payload, tmp_path / "index.html")

    assert path.read_text(encoding="utf-8") == page
    assert "Unofficial, not affiliated with Formula 1." in page
    assert "2.250" in page
    assert "4.458" in page
    assert "0.500" in page
    assert "50.0%" in page
    assert "0.667" in page
    assert "A &lt; B Grand Prix" in page
    assert "<script" not in page
    assert "googletagmanager" not in page
    assert "google-analytics" not in page


def test_openf1_backfill_stores_derived_rows_only(tmp_path: Path) -> None:
    transport = _Routes(
        {
            (f"{BASE}/meetings", (("year", "2026"),)): [
                {
                    "meeting_key": 99,
                    "meeting_name": "Pre-Season Testing",
                    "date_start": "2026-02-11T00:00:00+00:00",
                },
                {
                    "meeting_key": 5,
                    "meeting_name": "Australian Grand Prix",
                    "date_start": "2026-03-06T00:00:00+00:00",
                },
            ],
            (f"{BASE}/sessions", (("meeting_key", "5"),)): [
                {
                    "session_key": 9,
                    "session_name": "Qualifying",
                    "date_start": "2026-03-07T05:00:00+00:00",
                },
                {
                    "session_key": 10,
                    "session_name": "Race",
                    "date_start": "2026-03-08T04:00:00+00:00",
                },
            ],
            (f"{BASE}/session_result", (("session_key", "10"),)): [
                _result(63, 1, 58),
                _result(1, 2, 58),
            ],
            (f"{BASE}/pit", (("session_key", "10"),)): [
                {"driver_number": 63, "lap_number": 36, "pit_duration": 21.5},
                {"driver_number": 1, "lap_number": 30, "pit_duration": 22.0},
            ],
            (f"{BASE}/stints", (("session_key", "10"),)): [
                _stint(63, 1, 1, 36, "HARD"),
                _stint(63, 2, 37, 58, "SOFT"),
                _stint(1, 1, 1, 30, "MEDIUM"),
                _stint(1, 2, 31, 58, "HARD"),
            ],
            (f"{BASE}/drivers", (("session_key", "10"),)): [
                {"driver_number": 63, "name_acronym": "RUS"},
                {"driver_number": 1, "name_acronym": "NOR"},
            ],
            (f"{BASE}/session_result", (("session_key", "9"),)): [
                {"driver_number": 63, "position": 1, "duration": [78.518]},
                {"driver_number": 1, "position": 2, "duration": [78.8]},
            ],
        }
    )
    races = fetch_openf1(
        transport, season=2026, as_of="2026-10-16", sleep=lambda _seconds: None
    )
    payload = build_log(races, season=2026, as_of="2026-10-16")
    path = write_log(payload, tmp_path)
    text = path.read_text(encoding="utf-8")

    assert [call[0] for call in transport.calls].count(f"{BASE}/sessions") == 1
    assert races[0]["event_name"] == "Australian Grand Prix"
    assert payload["rates"]["pit_lap_mae"] == 3.0
    assert payload["rates"]["stint_length_mae"] == 3.0
    assert payload["rates"]["stop_count_mae"] == 0.0
    assert payload["rates"]["undercut_error_rate"] == 1.0
    assert payload["rates"]["finish_order_mae"] == 0.0
    assert payload["races"][0]["predicted_stop_laps"] == [36]
    assert payload["races"][0]["predicted_stint_laps"] == [36, 22]
    assert payload["notice"] == NOTICE
    assert "pit_duration" not in text
    assert "78.518" not in text
    assert "telemetry" not in text
    again = build_log(races, season=2026, as_of="2026-10-16", previous=payload)
    assert len(again["races"]) == 1


def test_openf1_stops_at_the_call_budget_and_retries_429() -> None:
    with pytest.raises(HistoricalSourceError, match="call budget"):
        fetch_openf1(
            _Routes(
                {
                    (f"{BASE}/meetings", (("year", "2026"),)): [
                        {"meeting_key": 5, "meeting_name": "Race"}
                    ]
                }
            ),
            season=2026,
            as_of="2026-10-16",
            budget=1,
            sleep=lambda _seconds: None,
        )

    sleeps: list[float] = []
    transport = _Once(
        HistoricalSourceError("Historical source returned HTTP 429 for meetings"),
        [],
    )
    assert (
        fetch_openf1(transport, season=2026, as_of="2026-10-16", sleep=sleeps.append)
        == []
    )
    assert sleeps == [20.0]


def test_fastf1_reader_keeps_derived_stints_and_skips_telemetry(tmp_path: Path) -> None:
    module = _FastF1()
    races = collect_fastf1(module, season=2026, as_of="2026-10-16", cache_dir=tmp_path)

    assert module.cached == str(tmp_path)
    assert module.requested == [(1, "R"), (1, "Q")]
    race_load, quali_load = module.loads
    assert race_load == {
        "laps": True,
        "telemetry": False,
        "weather": False,
        "messages": False,
    }
    assert quali_load["laps"] is False
    assert quali_load["telemetry"] is False
    assert len(races) == 1
    race = races[0]
    assert race["source"] == "fastf1"
    assert race["race_laps"] == 3
    assert race["wet_tyres_seen"] is False
    rus = race["drivers"][1]
    assert rus["code"] == "RUS"
    assert rus["stint_laps"] == [2, 1]
    assert rus["stop_laps"] == [2]
    assert rus["classified"] is True
    retired = race["drivers"][0]
    assert retired["code"] == "NOR"
    assert retired["status"] == "dnf"
    assert retired["classified"] is False


def test_accuracy_route_reads_the_stored_log(tmp_path: Path) -> None:
    write_log(
        {
            "season": 2026,
            "as_of": "2026-10-16",
            "notice": NOTICE,
            "honesty": "Not validated yet.",
            "assumption": "One pack.",
            "rates": {"races": 0, "pit_lap_mae": None},
            "races": [],
        },
        tmp_path,
    )
    client = TestClient(create_app(object(), accuracy_dir=tmp_path))

    found = client.get("/v1/accuracy/2026")
    missing = client.get("/v1/accuracy/2025")
    rejected = client.get("/v1/accuracy/1949")

    assert found.status_code == 200
    assert found.json()["notice"] == "Unofficial, not affiliated with Formula 1."
    assert missing.status_code == 404
    assert missing.json()["detail"] == "No accuracy log for 2025."
    assert rejected.status_code == 422


def test_log_path_stays_inside_the_data_directory(tmp_path: Path) -> None:
    from accuracy.publish import log_path

    assert log_path(2026, tmp_path) == Path(os.path.realpath(tmp_path)) / "2026.json"
    with pytest.raises(ValueError, match="1950"):
        log_path(1800, tmp_path)
    with pytest.raises(ValueError, match="integer"):
        log_path(True, tmp_path)  # type: ignore[arg-type]


def test_cli_writes_a_log_and_rejects_bad_input(tmp_path: Path, monkeypatch) -> None:
    from accuracy.__main__ import main

    monkeypatch.setattr("accuracy.__main__.fetch_openf1", lambda *_args, **_kwargs: [])
    page = tmp_path / "index.html"
    code = main(
        [
            "--season",
            "2026",
            "--as-of",
            "2026-10-16",
            "--data-dir",
            str(tmp_path),
            "--page",
            str(page),
        ]
    )

    assert code == 0
    stored = json.loads((tmp_path / "2026.json").read_text(encoding="utf-8"))
    assert stored["notice"] == NOTICE
    assert "Unofficial, not affiliated with Formula 1." in page.read_text(
        encoding="utf-8"
    )
    assert main(["--season", "1800"]) == 2
    assert main(["--as-of", "16-10-2026"]) == 2


def test_committed_2026_log_matches_its_rows() -> None:
    payload = read_log(2026)
    page = (
        Path(__file__).resolve().parent.parent / "docs" / "accuracy" / "index.html"
    ).read_text(encoding="utf-8")

    assert payload is not None
    assert payload["as_of"] == "2026-10-16"
    assert payload["notice"] == NOTICE
    assert payload["rates"] == season_rates(list(payload["races"]))
    assert payload["rates"] == {
        "races": 17,
        "strategy_races": 15,
        "undercut_pairs": 241,
        "undercut_hits": 144,
        "pit_lap_mae": 13.375,
        "stint_length_mae": 11.764,
        "stop_count_mae": 0.659,
        "undercut_error_rate": 0.402,
        "finish_order_mae": 1.8,
    }
    assert payload["races"][0]["event_name"] == "Australian Grand Prix"
    assert payload["races"][0]["race_date"] == "2026-03-08"
    assert payload["races"][0]["predicted_stop_laps"] == [36]
    assert payload["races"][-1]["event_name"] == "Singapore Grand Prix"
    assert all("Saudi" not in str(race["event_name"]) for race in payload["races"])
    assert all(str(race["race_date"]) <= "2026-10-16" for race in payload["races"])
    assert all(
        "United States" not in str(race["event_name"]) for race in payload["races"]
    )
    assert "Unofficial, not affiliated with Formula 1." in page
    assert f"{payload['rates']['pit_lap_mae']:.3f}" in page
    assert "<script" not in page


def _driver(
    code: str,
    number: int,
    quali: int | None,
    finish: int | None,
    stops: list[int],
    stints: list[int],
    *,
    classified: bool = True,
    status: str = "classified",
) -> dict[str, object]:
    return {
        "code": code,
        "driver_number": number,
        "qualifying_position": quali,
        "finish_position": finish,
        "classified": classified,
        "status": status,
        "stop_laps": stops,
        "stint_laps": stints,
    }


def _result(number: int, position: int, laps: int) -> dict[str, object]:
    return {
        "driver_number": number,
        "position": position,
        "number_of_laps": laps,
        "dnf": False,
        "dns": False,
        "dsq": False,
        "duration": 5000.0,
    }


def _stint(
    number: int, stint: int, start: int, end: int, compound: str
) -> dict[str, object]:
    return {
        "driver_number": number,
        "stint_number": stint,
        "lap_start": start,
        "lap_end": end,
        "compound": compound,
    }


class _Routes:
    def __init__(
        self, routes: dict[tuple[str, tuple[tuple[str, str], ...]], object]
    ) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> object:
        self.calls.append((url, dict(params)))
        key = (url, tuple(sorted(params.items())))
        if key not in self.routes:
            raise AssertionError(f"unexpected request {url} {params}")
        return self.routes[key]


class _Once:
    def __init__(self, first: Exception, second: object) -> None:
        self.first = first
        self.second = second
        self.calls = 0

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> object:
        self.calls += 1
        if self.calls == 1:
            raise self.first
        return self.second


class _FastF1:
    def __init__(self) -> None:
        self.cached: str | None = None
        self.loads: list[dict[str, object]] = []
        self.requested: list[tuple[int, str]] = []
        self.Cache = self

    def enable_cache(self, path: str) -> None:
        self.cached = path

    def get_event_schedule(self, season: int) -> list[dict[str, object]]:
        assert season == 2026
        return [
            {
                "EventFormat": "testing",
                "EventDate": "2026-02-11",
                "RoundNumber": 0,
                "EventName": "Pre-Season Testing",
            },
            {
                "EventFormat": "conventional",
                "EventDate": "2026-03-08",
                "RoundNumber": 1,
                "EventName": "Australian Grand Prix",
            },
            {
                "EventFormat": "conventional",
                "EventDate": "2026-10-25",
                "RoundNumber": 2,
                "EventName": "United States Grand Prix",
            },
        ]

    def get_session(self, season: int, round_: int, code: str) -> _Session:
        assert season == 2026
        if code == "R" and round_ == 1:
            session = _Session(
                [
                    {
                        "DriverNumber": 1,
                        "Abbreviation": "NOR",
                        "Position": 20,
                        "GridPosition": 2,
                        "Status": "Retired",
                    },
                    {
                        "DriverNumber": 63,
                        "Abbreviation": "RUS",
                        "Position": 1,
                        "GridPosition": 1,
                        "Status": "Finished",
                    },
                ],
                [
                    {
                        "DriverNumber": 63,
                        "Stint": 1,
                        "LapNumber": 1,
                        "Compound": "HARD",
                    },
                    {
                        "DriverNumber": 63,
                        "Stint": 1,
                        "LapNumber": 2,
                        "Compound": "HARD",
                    },
                    {
                        "DriverNumber": 63,
                        "Stint": 2,
                        "LapNumber": 3,
                        "Compound": "SOFT",
                    },
                ],
            )
        elif code == "Q" and round_ == 1:
            session = _Session([{"DriverNumber": 63, "Position": 1}])
        else:
            session = _Session([])
        session.loads = self.loads
        self.requested.append((round_, code))
        return session


class _Session:
    def __init__(
        self,
        results: list[dict[str, object]],
        laps: list[dict[str, object]] | None = None,
    ) -> None:
        self.results = results
        self.laps = laps or []
        self.loads: list[dict[str, object]] = []
        self.name = ""

    def load(self, **kwargs: object) -> None:
        self.loads.append(kwargs)
