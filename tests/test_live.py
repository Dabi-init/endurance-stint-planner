"""Replay is the free lap feed. The paid OpenF1 socket stays closed."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from engine.f1_odds import ODDS_HONESTY
from live.sources import TOKEN_ENV, LiveSourceError, describe_sources, iter_frames
from pitwall_api.app import create_app, pace_delay_sec


class _Transport:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def frames(self) -> Iterator[dict[str, object]]:
        yield from self.rows


def _client() -> TestClient:
    return TestClient(create_app(object()))


def test_replay_frames_follow_the_recorded_bahrain_stints() -> None:
    frames = list(iter_frames("replay"))
    pit = frames[16]
    green = frames[0]

    assert len(frames) == 57
    assert green["live"] is False
    assert green["kind"] == "green"
    assert green["source"] == "replay"
    assert pit["lap"] == 17
    assert pit["kind"] == "pit"
    assert pit["message"] == "Lap 17 is a recorded pit. Soft comes off."
    assert pit["race_time_sec"] == 3832.01


def test_safety_car_window_saves_twelve_seconds_on_the_replay() -> None:
    frames = list(
        iter_frames(
            "replay",
            safety_car={"start_lap": 34, "end_lap": 36, "pit_loss_sec": 10},
        )
    )
    quiet = list(
        iter_frames(
            "replay",
            safety_car={
                "kind": "vsc",
                "start_lap": 20,
                "end_lap": 23,
                "pit_loss_sec": 14,
                "pull_pit_into_sc": True,
            },
        )
    )

    assert frames[33]["kind"] == "safety-car"
    assert "saving 12.000 s" in frames[34]["message"]
    assert frames[34]["alert"] == frames[34]["message"].split(". ", 1)[1]
    assert quiet[19]["kind"] == "vsc"
    assert quiet[19]["message"].startswith("Virtual safety car laps 20–23.")
    assert "Estimated time saved: 0 s." in quiet[19]["message"]


def test_live_source_errors_stay_safe() -> None:
    with pytest.raises(LiveSourceError, match="safety-car or vsc"):
        list(
            iter_frames(
                "replay",
                safety_car={
                    "kind": "red-flag",
                    "start_lap": 1,
                    "end_lap": 2,
                    "pit_loss_sec": 10,
                },
            )
        )
    with pytest.raises(LiveSourceError, match="start_lap"):
        list(iter_frames("replay", safety_car={"start_lap": 1}))
    with pytest.raises(LiveSourceError, match="Unknown live source"):
        list(iter_frames("timing-radio"))
    with pytest.raises(LiveSourceError, match="Use the replay source"):
        list(iter_frames("openf1"))


def test_openf1_token_never_leaves_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "super-secret-token"
    monkeypatch.setenv(TOKEN_ENV, secret)
    listed = json.dumps(describe_sources())
    assert secret not in listed
    assert "not sent to the browser" in listed

    with pytest.raises(LiveSourceError, match="not opened by default"):
        list(iter_frames("openf1"))
    leaked = list(
        iter_frames("openf1", transport=_Transport([{"lap": 1, "message": "clear"}]))
    )
    assert leaked == [{"lap": 1, "message": "clear"}]
    with pytest.raises(LiveSourceError, match="secret and was dropped"):
        list(
            iter_frames(
                "openf1",
                transport=_Transport([{"lap": 1, "message": secret}]),
            )
        )
    with pytest.raises(LiveSourceError, match="secret and was dropped"):
        list(iter_frames("openf1", transport=_Transport([{TOKEN_ENV: "hidden"}])))


def test_sources_without_a_token_name_the_free_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    rows = {row["id"]: row for row in describe_sources()}

    assert rows["replay"]["available"] is True
    assert rows["replay"]["connected"] is True
    assert rows["openf1"]["available"] is False
    assert "No server token" in str(rows["openf1"]["detail"])


def test_live_http_replay_undercut_and_odds() -> None:
    client = _client()
    frames = client.get(
        "/v1/live/replay/frames", params={"sc_start": 34, "sc_end": 36, "sc_pit": 10}
    )
    partial = client.get("/v1/live/replay/frames", params={"sc_start": 34})
    unknown = client.get("/v1/live/nope/frames")
    paid = client.get("/v1/live/openf1/frames")
    under = client.post(
        "/v1/f1/undercut",
        json={
            "gap_behind_sec": 2,
            "laps_ahead": 5,
            "tyre_gain_sec_per_lap": 0.5,
            "our_pit_loss_sec": 22,
            "their_pit_loss_sec": 22,
        },
    )
    odds = client.post(
        "/v1/f1/odds", json={"season": 2024, "round": 1, "iterations": 64}
    )
    too_many = client.post(
        "/v1/f1/odds", json={"season": 2024, "round": 1, "iterations": 900}
    )
    missing = client.post(
        "/v1/f1/odds", json={"season": 1800, "round": 1, "iterations": 8}
    )

    assert frames.status_code == 200
    body = frames.json()
    assert len(body) == 57
    assert "saving 12.000 s" in body[34]["message"]
    assert partial.status_code == 400
    assert unknown.status_code == 400
    assert paid.status_code == 400
    assert "super-secret-token" not in paid.text
    assert under.json()["net_sec"] == 0.5
    assert under.json()["explanation"] == (
        "Pit 5 laps earlier and this rival is 0.500 s behind when they stop."
    )
    assert odds.status_code == 200
    sampled = odds.json()
    assert sampled["p10_sec"] == 5463.525
    assert sampled["p50_sec"] == 5466.352
    assert sampled["p90_sec"] == 5468.666
    assert sampled["compounds"] == ["HARD", "SOFT"]
    assert sampled["stint_laps"] == [35, 22]
    assert sampled["honesty"] == ODDS_HONESTY
    assert too_many.status_code == 422
    assert missing.status_code == 404
    assert sampled["label"] == "Race-time spread"
    negative_gap = client.post(
        "/v1/f1/undercut",
        json={
            "gap_behind_sec": -1,
            "laps_ahead": 5,
            "tyre_gain_sec_per_lap": 0.5,
            "our_pit_loss_sec": 22,
            "their_pit_loss_sec": 22,
        },
    )
    negative_pit = client.post(
        "/v1/f1/undercut",
        json={
            "gap_behind_sec": 2,
            "laps_ahead": 5,
            "tyre_gain_sec_per_lap": 0.5,
            "our_pit_loss_sec": -1,
            "their_pit_loss_sec": 22,
        },
    )
    reversed_window = client.get(
        "/v1/live/replay/frames",
        params={"sc_start": 36, "sc_end": 34, "sc_pit": 10},
    )
    negative_sc = client.get(
        "/v1/live/replay/frames",
        params={"sc_start": 34, "sc_end": 36, "sc_pit": -1},
    )
    assert negative_gap.status_code == 422
    assert negative_pit.status_code == 422
    assert reversed_window.status_code == 422
    assert "end_lap" in reversed_window.json()["detail"]
    assert negative_sc.status_code == 422
    assert "pit_loss_sec" in negative_sc.json()["detail"]


def test_replay_stream_is_server_sent_events(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("pitwall_api.app._pace", record)
    client = _client()
    quiet = client.get("/v1/live/replay/stream")
    paced = client.get("/v1/live/replay/stream", params={"pace_ms": 50_000})

    assert quiet.status_code == 200
    assert quiet.headers["content-type"].startswith("text/event-stream")
    assert quiet.text.count("data: ") == 57
    assert "saving 12.000 s" not in quiet.text
    assert paced.status_code == 200
    assert slept == [2.0] * 57
    assert pace_delay_sec(-5) == 0
    assert pace_delay_sec(1) == 0.001
    assert pace_delay_sec(9_000) == 2.0
