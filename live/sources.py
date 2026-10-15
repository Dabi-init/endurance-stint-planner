"""Live feeds.

Replay plays a recorded race from the local fixture. OpenF1's live socket is a
paid product: the token stays in the server environment, never in a response,
and this process does not open that socket unless a caller supplies a transport.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any, Protocol

from engine.f1 import SafetyCarRequest, best_f1_plan, replan_f1_safety_car
from engine.series_config import load_setup
from replay.session import build_replay

TOKEN_ENV = "OPENF1_LIVE_TOKEN"


class LiveSourceError(RuntimeError):
    """A live feed cannot be played. The message is safe to show."""


class FrameTransport(Protocol):
    def frames(self) -> Iterator[dict[str, Any]]:
        """Yield already-public frame dicts. Must not include secrets."""


def describe_sources() -> list[dict[str, object]]:
    token = os.environ.get(TOKEN_ENV, "")
    if token:
        openf1 = {
            "id": "openf1",
            "available": True,
            "connected": False,
            "detail": (
                "A server-side OpenF1 live token is set. It is not sent to the browser. "
                "The paid live socket stays closed until a transport is plugged in. "
                "Replay remains the free path."
            ),
        }
    else:
        openf1 = {
            "id": "openf1",
            "available": False,
            "connected": False,
            "detail": (
                "OpenF1 live is a paid feed. No server token is configured. "
                "Historical OpenF1 data stays on the free replay path."
            ),
        }
    return [
        {
            "id": "replay",
            "available": True,
            "connected": True,
            "detail": (
                "Plays the bundled 2024 Bahrain Grand Prix from the local fixture. "
                "The browser can pause, change speed, and jump to a lap. "
                "This is a recording, not live timing."
            ),
        },
        openf1,
    ]


def iter_frames(
    source_id: str,
    *,
    safety_car: dict[str, Any] | None = None,
    transport: FrameTransport | None = None,
) -> Iterator[dict[str, Any]]:
    if source_id == "replay":
        yield from _replay_frames(safety_car)
        return
    if source_id == "openf1":
        yield from _openf1_frames(transport)
        return
    known = ", ".join(row["id"] for row in describe_sources())  # type: ignore[misc]
    raise LiveSourceError(f"Unknown live source {source_id}. Known sources: {known}.")


def _openf1_frames(transport: FrameTransport | None) -> Iterator[dict[str, Any]]:
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise LiveSourceError(
            "OpenF1 live is a paid feed. No server token is configured. Use the replay source."
        )
    if transport is None:
        raise LiveSourceError(
            "The OpenF1 live socket is not opened by default. Plug in a transport on the server."
        )
    for frame in transport.frames():
        if TOKEN_ENV in frame or token in str(frame.values()):
            raise LiveSourceError("A live frame included a secret and was dropped.")
        yield frame


def _replay_frames(safety_car: dict[str, Any] | None) -> Iterator[dict[str, Any]]:
    script = build_replay()
    payload = script.payload
    alert = _safety_alert(safety_car)
    events = {event["lap"]: event for event in payload["events"]}
    radio = _radio_by_lap(payload.get("radio") or [])
    for lap in payload["laps"]:
        number = int(lap["lap"])
        kind = "pit" if lap["pit"] else "green"
        message = f"Lap {number}. {lap['compound'].title()}."
        if lap["pit"]:
            message = (
                f"Lap {number} is a recorded pit. {lap['compound'].title()} comes off."
            )
        plan = events.get(number) or _latest(payload["events"], number)
        sc_text = None
        if alert is not None and alert["start_lap"] <= number <= alert["end_lap"]:
            kind = alert["kind"]
            sc_text = alert["summary"]
            message = f"{alert['label']} laps {alert['start_lap']}–{alert['end_lap']}. {sc_text}"
        yield {
            "source": "replay",
            "live": False,
            "lap": number,
            "kind": kind,
            "compound": lap["compound"],
            "colour": lap["colour"],
            "message": message,
            "alert": sc_text,
            "plan_summary": None if plan is None else plan["summary"],
            "race_time_sec": None if plan is None else plan["race_time_sec"],
            "explanation": None if plan is None else plan["explanation"],
            "radio_urls": radio.get(number, []),
        }


def _radio_by_lap(clips: list[Any]) -> dict[int, list[str]]:
    """Keep every https clip on its lap. Other URLs never reach a frame."""
    found: dict[int, list[str]] = {}
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        url = clip.get("recording_url")
        lap = clip.get("lap")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if isinstance(lap, bool) or not isinstance(lap, int):
            continue
        found.setdefault(lap, []).append(url)
    return found


def _latest(events: list[dict[str, Any]], lap: int) -> dict[str, Any] | None:
    chosen = None
    for event in events:
        if int(event["lap"]) <= lap:
            chosen = event
    return chosen


def _safety_alert(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    kind = str(raw.get("kind") or "safety-car")
    if kind not in {"safety-car", "vsc"}:
        raise LiveSourceError("Safety car kind must be safety-car or vsc.")
    try:
        request = SafetyCarRequest(
            start_lap=int(raw["start_lap"]),
            end_lap=int(raw["end_lap"]),
            pit_loss_sec=float(raw["pit_loss_sec"]),
            pull_pit_into_sc=bool(raw.get("pull_pit_into_sc", True)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveSourceError(
            "Safety car needs start_lap, end_lap, and pit_loss_sec."
        ) from exc
    setup = load_setup(2024, 1)
    result = replan_f1_safety_car(best_f1_plan(setup), request)
    label = "Safety car" if kind == "safety-car" else "Virtual safety car"
    return {
        "kind": kind,
        "label": label,
        "start_lap": request.start_lap,
        "end_lap": request.end_lap,
        "summary": result.summary,
        "time_saved_sec": result.time_saved_sec,
    }
