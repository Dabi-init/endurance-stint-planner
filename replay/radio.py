"""OpenF1 team-radio links for a replay. Audio bytes are not stored."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

RADIO_NOTE = (
    "OpenF1 team-radio links for car 1. The browser plays the recording. "
    "Audio files are not stored."
)

_RADIO_FILES = {
    "2024-r01-bahrain-verstappen": (
        Path(__file__).resolve().parent.parent
        / "backtest"
        / "fixtures"
        / "2024_r01_bahrain_radio.json"
    ),
}


def load_radio(fixture_id: str) -> list[dict[str, Any]]:
    """Return synced clips for a known fixture. Unknown fixtures have no radio."""
    path = _RADIO_FILES.get(fixture_id)
    if path is None or not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    starts = [
        (int(row["lap"]), str(row["date_start"]))
        for row in document.get("lap_starts", [])
        if isinstance(row, dict) and row.get("lap") and row.get("date_start")
    ]
    return assign_clips(starts, document.get("clips") or [])


def assign_clips(
    lap_starts: list[tuple[int, str]],
    clips: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map each clip onto the lap that had already started at the clip time.

    ``lap_starts`` is ``(lap number, ISO date_start)``. A clip before the first
    lap stays on lap 1. Only https recording URLs are kept.
    """
    starts = sorted((int(lap), _parse(stamp)) for lap, stamp in lap_starts if stamp)
    assigned: list[dict[str, Any]] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        url = clip.get("recording_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        stamp = clip.get("date")
        if not isinstance(stamp, str) or not stamp:
            continue
        when = _parse(stamp)
        lap = starts[0][0] if starts else 1
        for number, start in starts:
            if start <= when:
                lap = number
            else:
                break
        assigned.append(
            {
                "lap": lap,
                "date": stamp,
                "driver_number": clip.get("driver_number"),
                "recording_url": url,
            }
        )
    return assigned


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
