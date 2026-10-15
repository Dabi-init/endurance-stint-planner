"""One interface over OpenF1 and Jolpica.

OpenF1 supplies headshot URLs and team colours. Jolpica supplies the round
number, the official race time, and pit-stop laps. Neither image file is
downloaded.
"""

from __future__ import annotations

from typing import Any

from engine.series_config import EntryDriver, EntryList, EntryTeam
from historical.errors import HistoricalSourceError
from historical.jolpica import JolpicaClient
from historical.models import ActualStint, CalendarEvent, RaceActuals
from historical.openf1 import OpenF1Client
from historical.terms import HISTORICAL_TERMS, JOLPICA_TERMS, OPENF1_TERMS


class F1History:
    name = "openf1+jolpica"
    terms = HISTORICAL_TERMS

    def __init__(self, transport: Any) -> None:
        self.openf1 = OpenF1Client(transport)
        self.jolpica = JolpicaClient(transport)

    def fetch_calendar(self, season: int) -> list[CalendarEvent]:
        races = self.jolpica.races(season)
        meetings = {
            str(meeting.get("meeting_name")): meeting
            for meeting in self.openf1.meetings(season)
        }
        events: list[CalendarEvent] = []
        for race in races:
            meeting = meetings.get(str(race.get("raceName")))
            circuit = race.get("Circuit") or {}
            location = circuit.get("Location") or {}
            events.append(
                CalendarEvent(
                    season=int(race.get("season", season)),
                    round=int(race["round"]),
                    event_name=str(race.get("raceName") or ""),
                    circuit_id=str(circuit.get("circuitId") or ""),
                    race_date=str(race.get("date") or ""),
                    meeting_key=None
                    if meeting is None
                    else int(meeting["meeting_key"]),
                    country_name=str(
                        (meeting or {}).get("country_name")
                        or location.get("country")
                        or ""
                    ),
                )
            )
        return events

    def fetch_entry_list(self, season: int, round_: int) -> EntryList:
        event = self._event(season, round_)
        drivers = self._openf1_drivers(event)
        source = "openf1"
        if not drivers:
            drivers = self._jolpica_drivers(season, round_)
            source = "jolpica"
        if not drivers:
            raise HistoricalSourceError(
                f"No entry list for {season} round {round_} from OpenF1 or Jolpica."
            )
        teams = _teams_from_drivers(drivers)
        return EntryList(
            season=season,
            round=round_,
            event_name=event.event_name,
            drivers=tuple(drivers),
            teams=tuple(teams),
            source_name=source,
            terms=self.terms,
        )

    def fetch_race_actuals(
        self, season: int, round_: int, driver_number: int
    ) -> RaceActuals:
        event = self._event(season, round_)
        if event.meeting_key is None:
            raise HistoricalSourceError(
                f"No OpenF1 meeting is linked to {season} round {round_}."
            )
        session = self.openf1.race_session(event.meeting_key)
        stint_rows = self.openf1.stints(int(session["session_key"]), driver_number)
        if not stint_rows:
            raise HistoricalSourceError(f"No OpenF1 stints for car {driver_number}.")
        identity = {
            driver.driver_number: driver for driver in self._openf1_drivers(event)
        }
        card = identity.get(driver_number)
        results = self.jolpica.results(season, round_)
        result = next(
            (row for row in results if str(row.get("number")) == str(driver_number)),
            None,
        )
        if result is None:
            raise HistoricalSourceError(
                f"Jolpica has no result for car {driver_number} in {season} round {round_}."
            )
        driver = result.get("Driver") or {}
        constructor = result.get("Constructor") or {}
        driver_id = str(driver.get("driverId") or "")
        pits = [
            row
            for row in self.jolpica.pitstops(season, round_)
            if str(row.get("driverId")) == driver_id
        ]
        pits.sort(key=lambda row: int(row["lap"]))
        stints = tuple(
            _stint(row)
            for row in sorted(stint_rows, key=lambda row: row["stint_number"])
        )
        stop_laps = tuple(int(row["lap"]) for row in pits) or tuple(
            stint.lap_end for stint in stints[:-1]
        )
        time_block = result.get("Time") or {}
        race_time = None
        if time_block.get("millis") is not None:
            race_time = int(time_block["millis"]) / 1000
        jolpica_name = (
            f"{driver.get('givenName', '')} {driver.get('familyName', '')}".strip()
        )
        laps_value = result.get("laps")
        race_laps = int(laps_value) if laps_value not in (None, "") else 0
        return RaceActuals(
            season=season,
            round=round_,
            event_name=event.event_name,
            driver_number=driver_number,
            driver_code=str((card.code if card else "") or driver.get("code") or ""),
            full_name=(card.full_name if card and card.full_name else jolpica_name),
            team_name=(
                card.team_name
                if card and card.team_name
                else str(constructor.get("name") or "")
            ),
            team_colour=None if card is None else card.team_colour,
            headshot_url=None if card is None else card.headshot_url,
            race_laps=race_laps,
            race_time_sec=race_time,
            race_time_text=time_block.get("time"),
            stints=stints,
            stop_laps=stop_laps,
            pit_durations_sec=tuple(float(row["duration"]) for row in pits),
            clean_lap_durations_sec=(),
            terms=f"{OPENF1_TERMS} {JOLPICA_TERMS}",
            sources=(
                f"OpenF1 stints session {session.get('session_key')} driver {driver_number}",
                f"Jolpica-F1 {season} round {round_} results and pitstops (CC BY-NC-SA 4.0)",
            ),
            retrieved_on="",
            country_code=None if card is None else card.country_code,
        )

    def _event(self, season: int, round_: int) -> CalendarEvent:
        matches = [
            event for event in self.fetch_calendar(season) if event.round == round_
        ]
        if not matches:
            raise HistoricalSourceError(f"No calendar row for {season} round {round_}.")
        return matches[0]

    def _openf1_drivers(self, event: CalendarEvent) -> list[EntryDriver]:
        if event.meeting_key is None:
            return []
        session = self.openf1.race_session(event.meeting_key)
        rows = self.openf1.drivers(int(session["session_key"]))
        drivers: list[EntryDriver] = []
        for row in rows:
            code = str(row.get("name_acronym") or "").upper()
            if not code:
                continue
            drivers.append(
                EntryDriver(
                    code=code,
                    driver_number=int(row["driver_number"]),
                    full_name=str(row.get("full_name") or ""),
                    team_name=str(row.get("team_name") or ""),
                    team_colour=row.get("team_colour"),
                    headshot_url=row.get("headshot_url"),
                    country_code=row.get("country_code"),
                    first_name=str(row.get("first_name") or ""),
                    last_name=str(row.get("last_name") or ""),
                )
            )
        return drivers

    def _jolpica_drivers(self, season: int, round_: int) -> list[EntryDriver]:
        drivers: list[EntryDriver] = []
        for row in self.jolpica.results(season, round_):
            person = row.get("Driver") or {}
            constructor = row.get("Constructor") or {}
            code = str(person.get("code") or "").upper()
            if not code:
                continue
            drivers.append(
                EntryDriver(
                    code=code,
                    driver_number=int(row["number"]),
                    full_name=f"{person.get('givenName', '')} {person.get('familyName', '')}".strip(),
                    team_name=str(constructor.get("name") or ""),
                    team_colour=None,
                    headshot_url=None,
                    country_code=None,
                    first_name=str(person.get("givenName") or ""),
                    last_name=str(person.get("familyName") or ""),
                )
            )
        return drivers


def _teams_from_drivers(drivers: list[EntryDriver]) -> list[EntryTeam]:
    teams: list[EntryTeam] = []
    seen: set[str] = set()
    for driver in drivers:
        if not driver.team_name or driver.team_name in seen:
            continue
        seen.add(driver.team_name)
        teams.append(
            EntryTeam(
                team_name=driver.team_name,
                team_colour=driver.team_colour,
                livery_image_url=None,
            )
        )
    return teams


def _stint(row: dict[str, Any]) -> ActualStint:
    lap_start = int(row["lap_start"])
    lap_end = int(row["lap_end"])
    return ActualStint(
        compound=str(row["compound"]).upper(),
        laps=lap_end - lap_start + 1,
        lap_start=lap_start,
        lap_end=lap_end,
        tyre_age_at_start=int(row.get("tyre_age_at_start") or 0),
    )
