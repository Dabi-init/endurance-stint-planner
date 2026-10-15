"""Team-radio links and the optional personal-use WEC timing adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from historical.openf1 import OpenF1Client
from live.sources import LiveSourceError, iter_frames
from live.wec import (
    WEC_NOTICE,
    WEC_PAGE,
    PublicWecTransport,
    bootstrap_url,
    choose_wec_session,
    project_timing,
    read_wec,
    session_id,
)
from pitwall_api.app import create_app
from replay.radio import assign_clips, load_radio
from replay.session import build_replay

ROOT = Path(__file__).resolve().parent.parent
RADIO = ROOT / "backtest" / "fixtures" / "2024_r01_bahrain_radio.json"


class _Transport:
    def __init__(self, listed: object, snapshot: object | None = None) -> None:
        self.listed = listed
        self.snapshot = snapshot
        self.urls: list[str] = []

    def get_json(self, url: str, params: dict[str, str]) -> object:
        self.urls.append(url)
        if url.endswith("/session-info/"):
            return self.listed
        return self.snapshot


def _session(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "seriesId": 10,
        "sid": 18110,
        "hideFromUsers": False,
        "isRaceSession": True,
        "isStarted": True,
        "startTime": "2026-06-14T14:00:00+00:00",
        "eventName": "Synthetic 6 Hours",
        "sessionName": "Race",
        "currentViewersCount": 99,
    }
    row.update(extra)
    return row


def _snapshot() -> dict[str, object]:
    return {
        "carLocations": [{"latitude": 1.0, "longitude": 2.0, "pid": "a"}],
        "commentatorPhraseLatest": {"text": "do not keep this"},
        "sessionInfo": {
            "sessionClasses": [{"classId": "hc", "className": "Hypercar"}],
        },
        "participants": [{"pid": "a", "teamName": "Example Team"}],
        "gaps": [
            {"pid": "a", "gapToFirstMillis": 0, "gapToFirstLaps": 0},
            {"pid": "b", "gapToFirstMillis": 1500, "gapToFirstLaps": 0},
            {"pid": "c", "gapToFirstMillis": 0, "gapToFirstLaps": 1},
            {"pid": "d", "gapToFirstMillis": 0, "gapToFirstLaps": 2},
        ],
        "laps": [
            {"pid": "a", "lapNumber": 3},
            {"pid": "a", "lapNumber": 10},
            {"pid": "b", "lapNumber": "nope"},
        ],
        "ranks": [
            {"pid": "a", "position": 1, "carNumber": "8", "classId": "hc"},
            {"pid": "gone", "position": 2, "carNumber": "7", "isDeleted": True},
            {
                "pid": "b",
                "position": 3,
                "carNumber": "5",
                "classId": "long-class-identifier",
            },
            {"pid": "c", "position": 4, "carNumber": "6", "classId": "LMGT3"},
            {"pid": "d", "position": 5, "carNumber": "51", "classId": "LMGT3"},
            "skip",
        ],
    }


def test_bahrain_radio_is_urls_synced_to_lap_start() -> None:
    raw = RADIO.read_bytes()
    document = json.loads(raw)
    starts = [(row["lap"], row["date_start"]) for row in document["lap_starts"]]
    synced = assign_clips(starts, document["clips"])
    loaded = load_radio("2024-r01-bahrain-verstappen")

    assert len(raw) < 20_000
    assert b"ID3" not in raw
    assert "Audio bytes were not downloaded" in document["source"]
    assert [row["lap"] for row in synced] == [4, 16, 36, 38]
    assert loaded == synced
    assert all(row["recording_url"].startswith("https://") for row in loaded)
    assert load_radio("not-a-fixture") == []
    assert "radio" in build_replay().payload
    assert build_replay().payload["radio"][1]["lap"] == 16


def test_assign_clips_keeps_https_and_the_open_lap() -> None:
    rows = assign_clips(
        [
            (1, "2024-03-02T15:00:00+00:00"),
            (2, "2024-03-02T15:02:00+00:00"),
        ],
        [
            {
                "date": "2024-03-02T14:59:00+00:00",
                "recording_url": "https://example.test/a.mp3",
                "driver_number": 1,
            },
            {
                "date": "2024-03-02T15:02:01+00:00",
                "recording_url": "http://example.test/b.mp3",
            },
            {
                "date": "2024-03-02T15:03:00+00:00",
                "recording_url": "https://example.test/c.mp3",
            },
            {"recording_url": "https://example.test/d.mp3"},
            "nope",
        ],
    )
    early = assign_clips(
        [],
        [
            {
                "date": "2024-03-02T15:00:00Z",
                "recording_url": "https://example.test/e.mp3",
            }
        ],
    )

    assert [row["lap"] for row in rows] == [1, 2]
    assert rows[0]["driver_number"] == 1
    assert early == [
        {
            "lap": 1,
            "date": "2024-03-02T15:00:00Z",
            "driver_number": None,
            "recording_url": "https://example.test/e.mp3",
        }
    ]


def test_replay_frames_carry_the_radio_link_for_that_lap() -> None:
    frames = list(iter_frames("replay"))

    assert frames[0]["radio_url"] is None
    assert frames[3]["radio_url"].startswith("https://")
    assert frames[3]["radio_url"].endswith(".mp3")
    assert frames[15]["lap"] == 16
    assert frames[15]["radio_url"].startswith("https://")


def test_openf1_team_radio_asks_for_metadata() -> None:
    seen: dict[str, object] = {}

    class Transport:
        def get_json(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> object:
            seen["url"] = url
            seen["params"] = params
            return [{"recording_url": "https://example.test/a.mp3"}]

    rows = OpenF1Client(Transport()).team_radio(9472, 1)

    assert seen["url"] == "https://api.openf1.org/v1/team_radio"
    assert seen["params"] == {"session_key": "9472", "driver_number": "1"}
    assert rows[0]["recording_url"].startswith("https://")


def test_wec_adapter_is_off_until_asked() -> None:
    class Boom:
        def get_json(self, url: str, params: dict[str, str]) -> object:
            raise AssertionError(url)

    quiet = read_wec(enabled=False, transport=Boom())

    assert quiet["fetched"] is False
    assert quiet["live"] is False
    assert quiet["stored"] is False
    assert quiet["page"] == WEC_PAGE
    assert quiet["audio"] == "not captured"
    assert quiet["video"] == "not captured"
    assert quiet["notice"] == WEC_NOTICE
    assert quiet["rows"] == []


def test_wec_adapter_ignores_other_series_and_keeps_classification_only() -> None:
    transport = _Transport(
        [
            {"seriesId": 379, "sid": 4, "sessionName": "Sim"},
            {"seriesId": 10, "sid": "18110", "isRaceSession": True},
            _session(),
            "nope",
        ],
        _snapshot(),
    )

    timing = read_wec(enabled=True, transport=transport)
    dumped = json.dumps(timing)

    assert transport.urls == [
        "https://insights.griiip.com/live/session-info/",
        "https://insights.griiip.com/api/v2/public/live/session/18110/bootstrap",
    ]
    assert timing["live"] is True
    assert timing["stored"] is False
    assert timing["session"]["event"] == "Synthetic 6 Hours"
    assert "currentViewersCount" not in dumped
    assert "latitude" not in dumped
    assert "commentator" not in dumped
    assert [row["car"] for row in timing["rows"]] == ["8", "5", "6", "51"]
    assert timing["rows"][0]["class_name"] == "Hypercar"
    assert timing["rows"][0]["lap"] == 10
    assert timing["rows"][0]["gap"] == "leader"
    assert timing["rows"][0]["team"] == "Example Team"
    assert timing["rows"][1]["gap"] == "+1.500 s"
    assert timing["rows"][1]["class_name"] == "Class"
    assert timing["rows"][2]["gap"] == "+1 lap"
    assert timing["rows"][3]["gap"] == "+2 laps"


def test_wec_adapter_reports_an_empty_public_page() -> None:
    transport = _Transport([{"seriesId": 229, "sid": 9, "hideFromUsers": False}])
    hidden = _Transport([_session(hideFromUsers=True)])

    empty = read_wec(enabled=True, transport=transport)
    also = read_wec(enabled=True, transport=hidden)

    assert empty["fetched"] is True
    assert empty["live"] is False
    assert empty["rows"] == []
    assert "No FIA WEC session" in empty["notice"]
    assert len(transport.urls) == 1
    assert also["live"] is False


def test_wec_adapter_rejects_a_bad_session_id_before_a_second_read() -> None:
    transport = _Transport([_session(sid="../etc/passwd")])

    with pytest.raises(LiveSourceError, match="did not name a session"):
        read_wec(enabled=True, transport=transport)
    with pytest.raises(LiveSourceError, match="did not name a session"):
        session_id({"sid": True})
    with pytest.raises(LiveSourceError, match="did not name a session"):
        bootstrap_url(0)

    assert transport.urls == ["https://insights.griiip.com/live/session-info/"]


def test_wec_adapter_errors_stay_safe() -> None:
    class Broken:
        def get_json(self, url: str, params: dict[str, str]) -> object:
            raise TimeoutError("slow")

    with pytest.raises(LiveSourceError, match="could not be read"):
        read_wec(enabled=True, transport=Broken())
    with pytest.raises(LiveSourceError, match="session list"):
        read_wec(enabled=True, transport=_Transport({"sessions": []}))
    with pytest.raises(LiveSourceError, match="timing table"):
        read_wec(enabled=True, transport=_Transport([_session()], ["nope"]))

    class Already:
        def get_json(self, url: str, params: dict[str, str]) -> object:
            raise LiveSourceError("Refused a redirect from the public timing host.")

    with pytest.raises(LiveSourceError, match="redirect"):
        read_wec(enabled=True, transport=Already())
    with pytest.raises(LiveSourceError, match="public WEC timing host"):
        PublicWecTransport().get_json("https://example.test/timing", {})


def test_public_transport_parses_json_and_refuses_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, status: int, payload: object) -> None:
            self.status_code = status
            self._payload = payload

        def json(self) -> object:
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    class Client:
        def __init__(self, status: int, payload: object) -> None:
            self.response = Response(status, payload)
            self.closed = False

        def get(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> Response:
            assert headers["Accept"] == "application/json"
            assert url.startswith("https://insights.griiip.com/")
            return self.response

        def close(self) -> None:
            self.closed = True

    ok = Client(200, [{"sid": 1}])
    assert PublicWecTransport(ok).get_json(  # type: ignore[arg-type]
        "https://insights.griiip.com/live/session-info/",
        {},
    ) == [{"sid": 1}]
    assert ok.closed is False
    with pytest.raises(LiveSourceError, match="redirect"):
        PublicWecTransport(Client(302, {})).get_json(  # type: ignore[arg-type]
            "https://insights.griiip.com/live/session-info/",
            {},
        )
    with pytest.raises(LiveSourceError, match="did not return a timing table"):
        PublicWecTransport(Client(404, {})).get_json(  # type: ignore[arg-type]
            "https://insights.griiip.com/live/session-info/",
            {},
        )
    with pytest.raises(LiveSourceError, match="did not return JSON"):
        PublicWecTransport(Client(200, json.JSONDecodeError("bad", "doc", 0))).get_json(  # type: ignore[arg-type]
            "https://insights.griiip.com/live/session-info/",
            {},
        )

    closed: dict[str, bool] = {}

    class Owned:
        def __init__(self, timeout: float, follow_redirects: bool) -> None:
            assert follow_redirects is False

        def get(
            self, url: str, params: dict[str, str], headers: dict[str, str]
        ) -> Response:
            return Response(200, {"ok": True})

        def close(self) -> None:
            closed["closed"] = True

    monkeypatch.setattr("live.wec.httpx.Client", Owned)
    assert PublicWecTransport().get_json(
        "https://insights.griiip.com/live/session-info/",
        {},
    ) == {"ok": True}
    assert closed["closed"] is True


def test_choose_wec_session_prefers_a_started_race() -> None:
    practice = _session(
        isRaceSession=False,
        isStarted=True,
        startTime="2026-06-15T09:00:00+00:00",
        sid=2,
    )
    earlier = _session(startTime="2026-06-14T12:00:00+00:00", sid=3, isStarted=False)
    later = _session(startTime="2026-06-14T16:00:00+00:00", sid=4, isStarted=True)

    assert choose_wec_session([practice, earlier, later])["sid"] == 4
    assert choose_wec_session([practice])["sid"] == 2
    assert choose_wec_session([]) is None


def test_project_timing_caps_the_table_and_ignores_a_missing_rank_list() -> None:
    ranks = [
        {"pid": str(index), "position": index, "carNumber": str(index), "classId": "P"}
        for index in range(1, 62)
    ]
    rows = project_timing(
        {"ranks": ranks, "gaps": None, "laps": None, "participants": None}
    )

    assert project_timing({}) == []
    assert len(rows) == 60
    assert rows[-1]["position"] == 60
    assert rows[0]["gap"] == "—"
    assert rows[0]["class_name"] == "P"


def test_wec_http_does_not_fetch_until_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app(object()))
    off = client.get("/v1/live/wec")

    def fake(*, enabled: bool, transport: object = None) -> dict[str, object]:
        assert enabled is True
        assert transport is None
        return {
            "enabled": True,
            "fetched": True,
            "live": False,
            "rows": [],
            "notice": WEC_NOTICE,
            "stored": False,
        }

    monkeypatch.setattr("pitwall_api.app.read_wec", fake)
    on = client.get("/v1/live/wec", params={"enable": True})

    def explode(*, enabled: bool, transport: object = None) -> dict[str, object]:
        raise LiveSourceError(
            "The public timing page could not be read. Nothing was stored."
        )

    monkeypatch.setattr("pitwall_api.app.read_wec", explode)
    failed = client.get("/v1/live/wec", params={"enable": True})

    assert off.status_code == 200
    body = off.json()
    assert body["fetched"] is False
    assert body["notice"] == WEC_NOTICE
    assert body["page"] == WEC_PAGE
    assert on.status_code == 200
    assert on.json()["enabled"] is True
    assert failed.status_code == 502
    assert "Nothing was stored" in failed.json()["detail"]


def test_terms_include_the_wec_personal_use_notice() -> None:
    terms = TestClient(create_app(object())).get("/v1/terms")

    assert terms.status_code == 200
    assert terms.json()["wec"] == WEC_NOTICE
