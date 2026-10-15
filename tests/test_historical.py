"""Historical loader tests. Every response is a fixture; nothing uses the network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from engine.series_config import IMAGE_POLICY
from historical.cache import CachingTransport, FileCache, cache_key
from historical.catalogue import F1History
from historical.errors import HistoricalSourceError
from historical.http import HttpxTransport
from historical.jolpica import JolpicaClient
from historical.models import race_actuals_from_dict
from historical.openf1 import OpenF1Client
from historical.terms import USER_AGENT

HEADSHOT = (
    "https://media.formula1.com/d_driver_fallback_image.png/content/dam/"
    "fom-website/drivers/M/MAXVER01_Max_Verstappen/maxver01.png.transform/1col/image.png"
)


class RecordingTransport:
    def __init__(
        self, routes: dict[tuple[str, tuple[tuple[str, str], ...]], object]
    ) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> object:
        self.calls.append((url, dict(params), dict(headers)))
        key = (url, tuple(sorted(params.items())))
        if key not in self.routes:
            raise AssertionError(f"unexpected request {url} {params}")
        payload = self.routes[key]
        if isinstance(payload, Exception):
            raise payload
        return payload


def _mr(total: int, table: dict[str, object]) -> dict[str, object]:
    return {"MRData": {"total": str(total), "RaceTable": table}}


def _bahrain_routes(*, drivers: list[dict[str, object]] | None = None) -> dict:
    races = _mr(
        1,
        {
            "Races": [
                {
                    "season": "2024",
                    "round": "1",
                    "raceName": "Bahrain Grand Prix",
                    "date": "2024-03-02",
                    "Circuit": {
                        "circuitId": "bahrain",
                        "Location": {"country": "Bahrain"},
                    },
                }
            ]
        },
    )
    results = _mr(
        1,
        {
            "Races": [
                {
                    "Results": [
                        {
                            "number": "1",
                            "laps": "57",
                            "Driver": {
                                "driverId": "max_verstappen",
                                "code": "VER",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                            },
                            "Constructor": {"name": "Red Bull"},
                            "Time": {"millis": "5504742", "time": "1:31:44.742"},
                        }
                    ]
                }
            ]
        },
    )
    pits = [
        {"driverId": "max_verstappen", "lap": "37", "duration": "24.209"},
        {"driverId": "max_verstappen", "lap": "17", "duration": "25.064"},
        {"driverId": "other", "lap": "20", "duration": "22.0"},
    ]
    if drivers is None:
        drivers = [
            {
                "name_acronym": "VER",
                "driver_number": 1,
                "full_name": "Max VERSTAPPEN",
                "first_name": "Max",
                "last_name": "Verstappen",
                "team_name": "Red Bull Racing",
                "team_colour": "3671c6",
                "headshot_url": HEADSHOT,
                "country_code": "NED",
            },
            {
                "name_acronym": "",
                "driver_number": 99,
                "full_name": "No Code",
            },
        ]
    base_open = "https://api.openf1.org/v1"
    base_jolp = "https://api.jolpi.ca/ergast/f1"
    return {
        (f"{base_jolp}/2024.json", (("limit", "100"), ("offset", "0"))): races,
        (f"{base_open}/meetings", (("year", "2024"),)): [
            {
                "meeting_name": "Bahrain Grand Prix",
                "meeting_key": 1229,
                "country_name": "Bahrain",
                "date_start": "2024-02-29",
            }
        ],
        (
            f"{base_open}/sessions",
            (("meeting_key", "1229"), ("session_name", "Race")),
        ): [{"session_key": 9472, "session_name": "Race"}],
        (f"{base_open}/drivers", (("session_key", "9472"),)): drivers,
        (
            f"{base_open}/stints",
            (("driver_number", "1"), ("session_key", "9472")),
        ): [
            {
                "stint_number": 2,
                "compound": "HARD",
                "lap_start": 18,
                "lap_end": 37,
                "tyre_age_at_start": 0,
            },
            {
                "stint_number": 1,
                "compound": "SOFT",
                "lap_start": 1,
                "lap_end": 17,
                "tyre_age_at_start": 3,
            },
            {
                "stint_number": 3,
                "compound": "SOFT",
                "lap_start": 38,
                "lap_end": 57,
                "tyre_age_at_start": 0,
            },
        ],
        (
            f"{base_jolp}/2024/1/results.json",
            (("limit", "100"), ("offset", "0")),
        ): results,
        (f"{base_jolp}/2024/1/pitstops.json", (("limit", "100"), ("offset", "0"))): _mr(
            2,
            {"Races": [{"PitStops": pits}]},
        ),
    }


def test_entry_list_keeps_openf1_headshot_and_colour_without_downloading() -> None:
    transport = RecordingTransport(_bahrain_routes())
    entry = F1History(transport).fetch_entry_list(2024, 1)
    driver = entry.drivers[0]

    assert driver.code == "VER"
    assert driver.full_name == "Max VERSTAPPEN"
    assert driver.team_name == "Red Bull Racing"
    assert driver.team_colour == "3671c6"
    assert driver.headshot_url == HEADSHOT
    assert driver.country_code == "NED"
    assert entry.teams[0].livery_image_url is None
    assert entry.source_name == "openf1"
    assert all(call[2]["User-Agent"] == USER_AGENT for call in transport.calls)
    assert all("media.formula1.com" not in call[0] for call in transport.calls)
    assert "download" not in IMAGE_POLICY or "does not download" in IMAGE_POLICY


def test_race_actuals_use_official_time_and_both_pit_laps() -> None:
    actuals = F1History(RecordingTransport(_bahrain_routes())).fetch_race_actuals(
        2024, 1, 1
    )

    assert actuals.race_time_sec == 5504.742
    assert actuals.race_laps == 57
    assert [stint.laps for stint in actuals.stints] == [17, 20, 20]
    assert [stint.compound for stint in actuals.stints] == ["SOFT", "HARD", "SOFT"]
    assert actuals.stop_laps == (17, 37)
    assert actuals.pit_durations_sec == (25.064, 24.209)
    assert actuals.team_name == "Red Bull Racing"
    assert actuals.headshot_url == HEADSHOT
    assert actuals.team_colour == "3671c6"
    assert actuals.clean_lap_durations_sec == ()
    assert "CC BY-NC-SA 4.0" in actuals.terms


def test_jolpica_fallback_has_names_and_no_images() -> None:
    routes = _bahrain_routes(drivers=[])
    entry = F1History(RecordingTransport(routes)).fetch_entry_list(2024, 1)

    assert entry.source_name == "jolpica"
    assert entry.drivers[0].full_name == "Max Verstappen"
    assert entry.drivers[0].team_name == "Red Bull"
    assert entry.drivers[0].headshot_url is None
    assert entry.drivers[0].team_colour is None
    assert entry.teams[0].livery_image_url is None


def test_actuals_without_openf1_card_use_jolpica_identity() -> None:
    actuals = F1History(
        RecordingTransport(_bahrain_routes(drivers=[]))
    ).fetch_race_actuals(2024, 1, 1)

    assert actuals.full_name == "Max Verstappen"
    assert actuals.team_name == "Red Bull"
    assert actuals.headshot_url is None
    assert actuals.team_colour is None


def test_missing_pits_fall_back_to_stint_ends() -> None:
    routes = _bahrain_routes()
    routes[
        (
            "https://api.jolpi.ca/ergast/f1/2024/1/pitstops.json",
            (("limit", "100"), ("offset", "0")),
        )
    ] = _mr(0, {"Races": []})
    actuals = F1History(RecordingTransport(routes)).fetch_race_actuals(2024, 1, 1)

    assert actuals.stop_laps == (17, 37)
    assert actuals.pit_durations_sec == ()
    assert actuals.race_time_sec == 5504.742


def test_calendar_matches_meetings_by_name() -> None:
    events = F1History(RecordingTransport(_bahrain_routes())).fetch_calendar(2024)

    assert len(events) == 1
    assert events[0].meeting_key == 1229
    assert events[0].race_date == "2024-03-02"
    assert events[0].circuit_id == "bahrain"


def test_jolpica_pages_past_the_default_limit() -> None:
    pages = {
        "0": _mr(2, {"Races": [{"PitStops": [{"lap": "17"}]}]}),
        "1": _mr(2, {"Races": [{"PitStops": [{"lap": "37"}]}]}),
    }

    class Paged:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            assert headers["User-Agent"] == USER_AGENT
            return pages[params["offset"]]

    rows = JolpicaClient(Paged(), page_size=1).pitstops(2024, 1)

    assert [row["lap"] for row in rows] == ["17", "37"]


def test_jolpica_rejects_a_non_ergast_payload() -> None:
    class Bad:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            return {"detail": "nope"}

    with pytest.raises(HistoricalSourceError, match="unexpected payload"):
        JolpicaClient(Bad()).races(2024)


def test_page_cap_stops_a_runaway_total() -> None:
    class Endless:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            return _mr(50_000, {"Races": [{"round": "1"}]})

    with pytest.raises(HistoricalSourceError, match="page cap"):
        JolpicaClient(Endless(), page_size=5001).races(2024)


def test_openf1_dict_and_empty_session_are_errors() -> None:
    class DictPayload:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            return {"detail": "not a list"}

    with pytest.raises(HistoricalSourceError, match="not a list"):
        OpenF1Client(DictPayload()).meetings(2024)

    class Empty:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            return []

    with pytest.raises(HistoricalSourceError, match="no race session"):
        OpenF1Client(Empty()).race_session(1229)

    class Text:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            return "nope"

    with pytest.raises(HistoricalSourceError, match="unexpected payload"):
        OpenF1Client(Text()).meetings(2024)


def test_catalogue_errors_name_the_missing_piece() -> None:
    with pytest.raises(HistoricalSourceError, match="No calendar row"):
        F1History(RecordingTransport(_bahrain_routes())).fetch_entry_list(2024, 9)

    routes = _bahrain_routes(drivers=[])
    routes[
        (
            "https://api.jolpi.ca/ergast/f1/2024/1/results.json",
            (("limit", "100"), ("offset", "0")),
        )
    ] = _mr(0, {"Races": []})
    with pytest.raises(HistoricalSourceError, match="No entry list"):
        F1History(RecordingTransport(routes)).fetch_entry_list(2024, 1)

    meetings_only = {
        key: value
        for key, value in _bahrain_routes().items()
        if "meetings" in key[0] or key[0].endswith("/2024.json")
    }
    meetings_only[("https://api.openf1.org/v1/meetings", (("year", "2024"),))] = [
        {"meeting_name": "Other", "meeting_key": 1}
    ]
    with pytest.raises(HistoricalSourceError, match="No OpenF1 meeting"):
        F1History(RecordingTransport(meetings_only)).fetch_race_actuals(2024, 1, 1)

    no_stints = _bahrain_routes()
    no_stints[
        (
            "https://api.openf1.org/v1/stints",
            (("driver_number", "1"), ("session_key", "9472")),
        )
    ] = []
    with pytest.raises(HistoricalSourceError, match="No OpenF1 stints"):
        F1History(RecordingTransport(no_stints)).fetch_race_actuals(2024, 1, 1)

    no_result = _bahrain_routes()
    no_result[
        (
            "https://api.jolpi.ca/ergast/f1/2024/1/results.json",
            (("limit", "100"), ("offset", "0")),
        )
    ] = _mr(1, {"Races": [{"Results": [{"number": "44", "Driver": {"code": "HAM"}}]}]})
    with pytest.raises(HistoricalSourceError, match="no result for car 1"):
        F1History(RecordingTransport(no_result)).fetch_race_actuals(2024, 1, 1)


def test_http_refuses_redirects_and_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "https://example.invalid/elsewhere"}
        )

    client = httpx.Client(transport=httpx.MockTransport(redirect))
    transport = HttpxTransport(client, min_interval_sec=0)
    with pytest.raises(HistoricalSourceError, match="Refused a redirect"):
        transport.get_json("https://api.openf1.org/v1/meetings", {}, {})

    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "secret body"})

    client = httpx.Client(transport=httpx.MockTransport(missing))
    transport = HttpxTransport(client, min_interval_sec=0)
    with pytest.raises(HistoricalSourceError, match="HTTP 404") as caught:
        transport.get_json("https://api.openf1.org/v1/meetings", {}, {})
    assert "secret body" not in str(caught.value)

    def text(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = httpx.Client(transport=httpx.MockTransport(text))
    transport = HttpxTransport(client, min_interval_sec=0)
    with pytest.raises(HistoricalSourceError, match="did not return JSON"):
        transport.get_json("https://api.openf1.org/v1/meetings", {}, {})


def test_http_waits_out_the_rate_limit() -> None:
    waits: list[float] = []
    clock = {"now": 10.0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock["now"] += seconds

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(
        client,
        min_interval_sec=0.34,
        sleep=sleep,
        clock=lambda: clock["now"],
    )
    transport.get_json("https://api.openf1.org/v1/meetings", {"year": "2024"}, {})
    clock["now"] += 0.10
    transport.get_json("https://api.openf1.org/v1/meetings", {"year": "2024"}, {})

    assert waits == [pytest.approx(0.24)]


def test_cache_stores_success_and_skips_the_inner_call(tmp_path: Path) -> None:
    cache = FileCache(tmp_path)
    calls = {"n": 0}

    class Inner:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                raise HistoricalSourceError("down")
            return [{"ok": True}]

    wrapped = CachingTransport(Inner(), cache)
    with pytest.raises(HistoricalSourceError):
        wrapped.get_json("https://api.openf1.org/v1/meetings", {"year": "2024"}, {})
    assert list(tmp_path.glob("*.json")) == []

    first = wrapped.get_json("https://api.openf1.org/v1/meetings", {"year": "2024"}, {})
    second = wrapped.get_json(
        "https://api.openf1.org/v1/meetings", {"year": "2024"}, {}
    )

    assert first == second == [{"ok": True}]
    assert calls["n"] == 2
    stored = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["value"] == [{"ok": True}]
    assert cache.get(cache_key("https://example.test", {})) is None


def test_recorded_fixture_ignores_extra_keys_and_keeps_urls() -> None:
    body = {
        "season": 2024,
        "round": 1,
        "event_name": "Bahrain Grand Prix",
        "driver_number": 1,
        "driver_code": "VER",
        "race_laps": 57,
        "stints": [{"compound": "soft", "laps": 17, "lap_start": 1, "lap_end": 17}],
        "pace_method": "ignored",
        "headshot_url": HEADSHOT,
    }
    actuals = race_actuals_from_dict(body)

    assert actuals.stints[0].compound == "SOFT"
    assert actuals.headshot_url == HEADSHOT
    assert actuals.race_time_sec is None
