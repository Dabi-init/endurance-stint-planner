"""The local pit wall is a static page over the deterministic API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pitwall_api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(object()))


def test_home_page_is_the_pit_wall_and_has_no_tracker() -> None:
    client = _client()
    page = client.get("/")
    css = client.get("/static/wall.css")
    script = client.get("/static/wall.js")
    html = page.text

    assert page.status_code == 200
    assert "Timing tower" in html
    assert "Strategy timeline" in html
    assert "Scenario cards" in html
    assert "Your overrides" in html
    assert "Not live timing" in html
    assert html.count("<script") == 1
    assert 'src="/static/wall.js"' in html
    assert "googletagmanager" not in html
    assert "google-analytics" not in html
    assert css.status_code == 200
    assert script.status_code == 200
    assert "headshot" in script.text


def test_replay_endpoint_returns_the_bahrain_plan() -> None:
    client = _client()
    opened = client.get("/v1/replays/2024-r01-bahrain-verstappen")
    anchored = client.post(
        "/v1/replays/2024-r01-bahrain-verstappen",
        json={"anchor_pace": True},
    )
    missing = client.get("/v1/replays/not-a-fixture")

    assert opened.status_code == 200
    body = opened.json()
    assert body["events"][0]["race_time_sec"] == 5466.21
    assert body["events"][0]["pit_window"] == [35, 42]
    assert body["tower"][0]["headshot_url"].startswith("https://")
    assert anchored.json()["events"][0]["race_time_sec"] == 5496.363
    assert anchored.json()["pace_anchor_sec"] == 95.529
    assert missing.status_code == 404
