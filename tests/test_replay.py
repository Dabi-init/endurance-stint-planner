"""Exact replay frames for the bundled 2024 Bahrain Grand Prix."""

from __future__ import annotations

from pathlib import Path

from replay.session import ENTRY_FILES, build_replay

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "backtest" / "fixtures" / "2024_r01_bahrain_entry.json"
PRE_RACE = (
    "Before the lights, the file's fastest legal plan is the one below. "
    "One pit stop. 35 laps on the Hard tyre and 22 laps on the Soft tyre. "
    "Estimated race time 1:31:06.210. The car does not refuel during the race. "
    "A dry race in this rule file needs at least 2 different tyre types. "
    "This plan uses Hard and Soft. Every stint stays within the tyre life in the file."
)


def test_file_pace_replay_matches_the_event_file() -> None:
    payload = build_replay().payload
    opening, first_pit, second_pit = payload["events"]

    assert payload["race_laps"] == 57
    assert payload["anchor_pace"] is False
    assert payload["pace_anchor_sec"] is None
    assert len(payload["laps"]) == 57
    assert payload["laps"][16] == {
        "lap": 17,
        "compound": "SOFT",
        "colour": "FF1E00",
        "pit": True,
    }
    assert opening["race_time_sec"] == 5466.21
    assert opening["stop_laps"] == [35]
    assert opening["pit_window"] == [35, 42]
    assert [(row["compound"], row["laps"]) for row in opening["stints"]] == [
        ("HARD", 35),
        ("SOFT", 22),
    ]
    assert opening["explanation"] == PRE_RACE
    assert first_pit["lap"] == 17
    assert first_pit["race_time_sec"] == 3832.01
    assert first_pit["stop_laps"] == [21]
    assert first_pit["pit_window"] == [18, 32]
    assert [(row["compound"], row["laps"]) for row in first_pit["stints"]] == [
        ("MEDIUM", 21),
        ("SOFT", 19),
    ]
    assert second_pit["lap"] == 37
    assert second_pit["race_time_sec"] == 1903.4
    assert second_pit["stints"][0]["compound"] == "SOFT"
    assert second_pit["stints"][0]["laps"] == 20
    assert second_pit["pit_window"] is None
    assert "not a rewrite of history" in second_pit["explanation"]


def test_anchored_replay_matches_the_back_test_clock() -> None:
    opening = build_replay(anchor_pace=True).payload["events"][0]

    assert opening["race_time_sec"] == 5496.363
    assert opening["stop_laps"] == [35]
    assert "1:31:36.363" in opening["explanation"]


def test_tower_uses_openf1_links_and_no_image_bytes() -> None:
    raw = ENTRY.read_bytes()
    tower = build_replay().payload["tower"]

    assert len(raw) < 20_000
    assert b"\x89PNG" not in raw
    assert b"data:image" not in raw
    assert len(tower) == 20
    assert tower[0]["code"] == "VER"
    assert tower[0]["grid"] == 1
    assert tower[0]["team_colour_css"] == "#3671c6"
    assert tower[0]["headshot_url"].startswith("https://")
    assert tower[0]["focus"] is True
    assert "download" not in (tower[0]["headshot_url"])


def test_missing_entry_file_keeps_the_focus_car(monkeypatch) -> None:
    monkeypatch.setitem(
        ENTRY_FILES, "2024-r01-bahrain-verstappen", ENTRY.parent / "missing.json"
    )
    tower = build_replay().payload["tower"]

    assert len(tower) == 1
    assert tower[0]["code"] == "VER"
    assert tower[0]["headshot_url"].startswith("https://")
