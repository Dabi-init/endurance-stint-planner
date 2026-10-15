"""Recorded session facts. Image fields are URLs, never file bytes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActualStint:
    compound: str
    laps: int
    lap_start: int
    lap_end: int
    tyre_age_at_start: int = 0


@dataclass(frozen=True)
class CalendarEvent:
    season: int
    round: int
    event_name: str
    circuit_id: str
    race_date: str
    meeting_key: int | None
    country_name: str


@dataclass(frozen=True)
class RaceActuals:
    season: int
    round: int
    event_name: str
    driver_number: int
    driver_code: str
    full_name: str
    team_name: str
    team_colour: str | None
    headshot_url: str | None
    race_laps: int
    race_time_sec: float | None
    race_time_text: str | None
    stints: tuple[ActualStint, ...]
    stop_laps: tuple[int, ...]
    pit_durations_sec: tuple[float, ...]
    clean_lap_durations_sec: tuple[float, ...]
    terms: str
    sources: tuple[str, ...]
    retrieved_on: str
    livery_image_url: str | None = None
    country_code: str | None = None


def race_actuals_from_dict(body: dict[str, Any]) -> RaceActuals:
    stints = tuple(
        ActualStint(
            compound=str(row["compound"]).upper(),
            laps=int(row["laps"]),
            lap_start=int(row["lap_start"]),
            lap_end=int(row["lap_end"]),
            tyre_age_at_start=int(row.get("tyre_age_at_start", 0)),
        )
        for row in body["stints"]
    )
    return RaceActuals(
        season=int(body["season"]),
        round=int(body["round"]),
        event_name=str(body["event_name"]),
        driver_number=int(body["driver_number"]),
        driver_code=str(body["driver_code"]),
        full_name=str(body.get("full_name") or ""),
        team_name=str(body.get("team_name") or ""),
        team_colour=body.get("team_colour"),
        headshot_url=body.get("headshot_url"),
        livery_image_url=body.get("livery_image_url"),
        country_code=body.get("country_code"),
        race_laps=int(body["race_laps"]),
        race_time_sec=None
        if body.get("race_time_sec") is None
        else float(body["race_time_sec"]),
        race_time_text=body.get("race_time_text"),
        stints=stints,
        stop_laps=tuple(int(lap) for lap in body.get("stop_laps", [])),
        pit_durations_sec=tuple(
            float(value) for value in body.get("pit_durations_sec", [])
        ),
        clean_lap_durations_sec=tuple(
            float(value) for value in body.get("clean_lap_durations_sec", [])
        ),
        terms=str(body.get("terms") or ""),
        sources=tuple(str(item) for item in body.get("sources", [])),
        retrieved_on=str(body.get("retrieved_on") or ""),
    )
