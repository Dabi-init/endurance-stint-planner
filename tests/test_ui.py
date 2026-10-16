"""The local pit wall is a static page over the deterministic API."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from pitwall_api.app import create_app

ROOT = Path(__file__).resolve().parent.parent


def _client() -> TestClient:
    return TestClient(create_app(object()))


def test_home_page_is_the_pit_wall_and_has_no_tracker() -> None:
    client = _client()
    page = client.get("/")
    css = client.get("/static/wall.css")
    script = client.get("/static/wall.js")
    tower = client.get("/static/f1-view.js")
    html = page.text

    assert page.status_code == 200
    assert "Timing tower" in html
    assert "Strategy timeline" in html
    assert "Scenario cards" in html
    assert "Your overrides" in html
    assert "Not live timing" in html
    assert html.count("<script") == 1
    assert 'type="module" src="/static/wall.js"' in html
    assert "googletagmanager" not in html
    assert "google-analytics" not in html
    assert css.status_code == 200
    assert script.status_code == 200
    assert tower.status_code == 200
    assert "headshot" in tower.text
    assert "clampLap" in script.text
    assert "esc(driver.grid" in tower.text
    assert "esc(driver.finish_position" in tower.text
    assert 'from "./f1-view.js"' in script.text
    assert 'from "./endurance-view.js"' in script.text
    assert 'from "./accuracy-view.js"' in script.text
    assert 'id="mode-accuracy"' in html
    assert "Unofficial, not affiliated with Formula 1." in html
    accuracy = client.get("/static/accuracy-view.js")
    assert accuracy.status_code == 200
    assert "Unofficial, not affiliated with Formula 1." in accuracy.text
    assert 'hash.get("mode") === "accuracy"' in script.text
    assert "[hidden]" in css.text
    assert "display: none !important" in css.text
    assert "quiet.pause()" in tower.text
    assert 'quiet.removeAttribute("src")' in tower.text
    assert "quiet.load()" in tower.text
    assert 'audio.removeAttribute("src")' in tower.text
    assert "audio.load()" in tower.text
    assert 'if (state.series === "endurance") return;' in script.text
    mode = script.text.split("function setMode", 1)[1].split("function ", 1)[0]
    assert "pauseRecording()" in mode
    assert "esc(row.lap" in script.text


def test_replay_endpoint_returns_the_bahrain_plan() -> None:
    client = _client()
    opened = client.post(
        "/v1/replays/2024-r01-bahrain-verstappen",
        json={},
    )
    anchored = client.post(
        "/v1/replays/2024-r01-bahrain-verstappen",
        json={"anchor_pace": True},
    )
    missing = client.post("/v1/replays/not-a-fixture", json={})
    removed = client.get("/v1/replays/2024-r01-bahrain-verstappen")
    bad_override = client.post(
        "/v1/replays/2024-r01-bahrain-verstappen",
        json={"overrides": {"race_laps": "abc"}},
    )

    assert opened.status_code == 200
    body = opened.json()
    assert body["events"][0]["race_time_sec"] == 5466.21
    assert body["events"][0]["pit_window"] == [35, 42]
    assert body["tower"][0]["headshot_url"].startswith("https://")
    assert anchored.json()["events"][0]["race_time_sec"] == 5496.363
    assert anchored.json()["pace_anchor_sec"] == 95.529
    assert missing.status_code == 404
    assert removed.status_code == 405
    assert bad_override.status_code == 422
    assert "race_laps" in bad_override.json()["detail"]


def test_tower_escape_and_lap_clamp_run_in_node() -> None:
    completed = subprocess.run(
        ["node", "--test", str(ROOT / "tests" / "ui" / "escape.test.mjs")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
