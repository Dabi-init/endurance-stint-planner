"""Turn free post-session feeds into a small derived race.

OpenF1 is the scheduled source. FastF1 is an optional local reader. Neither
path writes raw laps, pit timestamps, or audio. Callers keep only the derived
race that ``score_race`` needs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from historical.errors import HistoricalSourceError
from historical.openf1 import OpenF1Client

# OpenF1's free tier allows 3 requests a second and 30 a minute. 2.1 seconds
# between calls stays under the minute cap. The budget stops a looping client.
OPENF1_CALL_BUDGET = 240
OPENF1_INTERVAL_SEC = 2.1
_RETRY_DELAYS = (20.0, 40.0, 60.0)

_WET = {"INTERMEDIATE", "WET"}


class CallBudget:
    """Count transport calls and stop before the free-tier budget is spent."""

    def __init__(self, transport: Any, limit: int = OPENF1_CALL_BUDGET) -> None:
        self.transport = transport
        self.limit = limit
        self.used = 0

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> Any:
        self.used += 1
        if self.used > self.limit:
            raise HistoricalSourceError(
                "Stopped before exceeding the OpenF1 call budget."
            )
        return self.transport.get_json(url, params, headers)


def fetch_openf1(
    transport: Any,
    *,
    season: int,
    as_of: str,
    budget: int = OPENF1_CALL_BUDGET,
    sleep: Callable[[float], None] | None = None,
) -> list[dict[str, object]]:
    """Completed race meetings on or before ``as_of``, oldest first.

    Testing meetings are skipped before any session call. A race with no
    result yet is skipped. One HTTP 429 is retried once.
    """
    pause = sleep or _sleep
    client = OpenF1Client(CallBudget(transport, budget))
    found: list[dict[str, object]] = []
    for meeting in _retry(lambda: client.meetings(season), pause):
        name = str(meeting.get("meeting_name") or "")
        if "testing" in name.lower():
            continue
        meeting_key = int(meeting["meeting_key"])
        sessions = _retry(lambda key=meeting_key: client.sessions(key), pause)
        race = _named(sessions, "Race")
        if race is None or race.get("is_cancelled"):
            continue
        race_date = str(race.get("date_start") or "")[:10]
        if not race_date or race_date > as_of:
            continue
        quali = _named(sessions, "Qualifying")
        session_key = int(race["session_key"])
        results = _retry(lambda key=session_key: client.session_result(key), pause)
        if not results:
            continue
        pits = _retry(lambda key=session_key: client.pits(key), pause)
        stints = _retry(lambda key=session_key: client.session_stints(key), pause)
        drivers = _retry(lambda key=session_key: client.drivers(key), pause)
        quali_rows: list[dict[str, Any]] = []
        if quali is not None and not quali.get("is_cancelled"):
            quali_key = int(quali["session_key"])
            quali_rows = _retry(lambda key=quali_key: client.session_result(key), pause)
        found.append(
            _from_openf1(
                event_name=name,
                race_date=race_date,
                meeting_key=meeting_key,
                results=results,
                pits=pits,
                stints=stints,
                drivers=drivers,
                qualifying=quali_rows,
            )
        )
    found.sort(key=lambda race: (str(race["race_date"]), str(race["event_name"])))
    for index, race in enumerate(found, start=1):
        race["round"] = index
    return found


def collect_fastf1(
    module: Any,
    *,
    season: int,
    as_of: str,
    cache_dir: Path,
) -> list[dict[str, object]]:
    """Read FastF1 in memory. The cache directory is the caller's temp dir.

    Race load asks for laps and refuses telemetry, weather, and messages.
    Qualifying load refuses laps as well. Nothing here writes a derived file.
    """
    module.Cache.enable_cache(str(cache_dir))
    rows = _records(module.get_event_schedule(season))
    races: list[dict[str, object]] = []
    for event in rows:
        if str(event.get("EventFormat") or "").lower() == "testing":
            continue
        race_date = str(event.get("EventDate") or "")[:10]
        if not race_date or race_date > as_of:
            continue
        round_ = _as_int(event.get("RoundNumber"))
        if round_ is None:
            continue
        session = module.get_session(season, round_, "R")
        session.load(laps=True, telemetry=False, weather=False, messages=False)
        quali = module.get_session(season, round_, "Q")
        quali.load(laps=False, telemetry=False, weather=False, messages=False)
        races.append(
            _from_fastf1(
                event_name=str(event.get("EventName") or f"Round {round_}"),
                race_date=race_date,
                round_=round_,
                results=_records(getattr(session, "results", None)),
                laps=_records(getattr(session, "laps", None)),
                qualifying=_records(getattr(quali, "results", None)),
            )
        )
    races.sort(key=lambda race: (str(race["race_date"]), int(race["round"])))
    return races


def _from_openf1(
    *,
    event_name: str,
    race_date: str,
    meeting_key: int,
    results: list[dict[str, Any]],
    pits: list[dict[str, Any]],
    stints: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    qualifying: list[dict[str, Any]],
) -> dict[str, object]:
    codes = {
        int(row["driver_number"]): str(row.get("name_acronym") or "")
        for row in drivers
        if _as_int(row.get("driver_number")) is not None
    }
    quali = {
        int(row["driver_number"]): int(row["position"])
        for row in qualifying
        if _as_int(row.get("driver_number")) is not None
        and _as_int(row.get("position")) is not None
    }
    race_laps = _race_laps(results)
    built: list[dict[str, object]] = []
    for row in results:
        number = _as_int(row.get("driver_number"))
        if number is None:
            continue
        status = _openf1_status(row)
        classified = status == "classified"
        built.append(
            {
                "code": codes.get(number) or f"#{number}",
                "driver_number": number,
                "qualifying_position": quali.get(number),
                "finish_position": _as_int(row.get("position")) if classified else None,
                "classified": classified,
                "status": status,
                "stop_laps": _stop_laps(pits, number),
                "stint_laps": _stint_laps(stints, number),
            }
        )
    built.sort(key=lambda driver: int(driver["driver_number"]))
    return {
        "round": 0,
        "event_name": event_name,
        "race_date": race_date,
        "meeting_key": meeting_key,
        "race_laps": race_laps,
        "source": "openf1",
        "wet_tyres_seen": _wet(stints),
        "drivers": built,
    }


def _from_fastf1(
    *,
    event_name: str,
    race_date: str,
    round_: int,
    results: list[dict[str, Any]],
    laps: list[dict[str, Any]],
    qualifying: list[dict[str, Any]],
) -> dict[str, object]:
    quali = {
        int(row["DriverNumber"]): int(row["Position"])
        for row in qualifying
        if _as_int(row.get("DriverNumber")) is not None
        and _as_int(row.get("Position")) is not None
    }
    grouped = _fastf1_stints(laps)
    race_laps = 0
    built: list[dict[str, object]] = []
    for row in results:
        number = _as_int(row.get("DriverNumber"))
        if number is None:
            continue
        status = _fastf1_status(row)
        classified = status == "classified"
        stint_laps, stop_laps = grouped.get(number, ((), ()))
        if classified:
            race_laps = max(race_laps, sum(stint_laps))
        code = str(row.get("Abbreviation") or "") or f"#{number}"
        grid = _as_int(row.get("GridPosition"))
        built.append(
            {
                "code": code,
                "driver_number": number,
                "qualifying_position": quali.get(number, grid),
                "finish_position": _as_int(row.get("Position")) if classified else None,
                "classified": classified,
                "status": status,
                "stop_laps": list(stop_laps),
                "stint_laps": list(stint_laps),
            }
        )
    if race_laps < 1:
        race_laps = max((sum(item["stint_laps"]) for item in built), default=0)
    built.sort(key=lambda driver: int(driver["driver_number"]))
    return {
        "round": round_,
        "event_name": event_name,
        "race_date": race_date,
        "meeting_key": None,
        "race_laps": race_laps,
        "source": "fastf1",
        "wet_tyres_seen": _wet_laps(laps),
        "drivers": built,
    }


def _fastf1_stints(
    laps: list[dict[str, Any]],
) -> dict[int, tuple[tuple[int, ...], tuple[int, ...]]]:
    """Group in-memory lap rows. The rows themselves are not returned."""
    by_driver: dict[int, dict[int, list[int]]] = {}
    for row in laps:
        number = _as_int(row.get("DriverNumber"))
        stint = _as_int(row.get("Stint"))
        lap = _as_int(row.get("LapNumber"))
        if number is None or stint is None or lap is None:
            continue
        by_driver.setdefault(number, {}).setdefault(stint, []).append(lap)
    grouped: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for number, stints in by_driver.items():
        ordered = [stints[key] for key in sorted(stints)]
        lengths = tuple(len(item) for item in ordered)
        stops = tuple(max(item) for item in ordered[:-1]) if len(ordered) > 1 else ()
        grouped[number] = (lengths, stops)
    return grouped


def _wet_laps(laps: list[dict[str, Any]]) -> bool:
    for row in laps:
        name = str(row.get("Compound") or "").upper()
        if name in _WET:
            return True
    return False


def _race_laps(results: list[dict[str, Any]]) -> int:
    classified = [
        int(row["number_of_laps"])
        for row in results
        if _openf1_status(row) == "classified" and _as_int(row.get("number_of_laps"))
    ]
    if classified:
        return max(classified)
    any_laps = [
        int(row["number_of_laps"])
        for row in results
        if _as_int(row.get("number_of_laps"))
    ]
    return max(any_laps, default=0)


def _stop_laps(rows: list[dict[str, Any]], driver_number: int) -> list[int]:
    laps = {
        int(row["lap_number"])
        for row in rows
        if _as_int(row.get("driver_number")) == driver_number
        and _as_int(row.get("lap_number")) is not None
    }
    return sorted(laps)


def _stint_laps(rows: list[dict[str, Any]], driver_number: int) -> list[int]:
    own = [
        row
        for row in rows
        if _as_int(row.get("driver_number")) == driver_number
        and _as_int(row.get("stint_number")) is not None
    ]
    own.sort(key=lambda row: int(row["stint_number"]))
    lengths: list[int] = []
    for row in own:
        start = _as_int(row.get("lap_start"))
        end = _as_int(row.get("lap_end"))
        if start is None or end is None or end < start:
            continue
        lengths.append(end - start + 1)
    return lengths


def _wet(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if str(row.get("compound") or "").upper() in _WET:
            return True
    return False


def _openf1_status(row: dict[str, Any]) -> str:
    if row.get("dns"):
        return "dns"
    if row.get("dsq"):
        return "dsq"
    if row.get("dnf"):
        return "dnf"
    return "classified"


def _fastf1_status(row: dict[str, Any]) -> str:
    status = str(row.get("Status") or "")
    lowered = status.lower()
    if "disqual" in lowered:
        return "dsq"
    if lowered in {"dns", "did not start", "withdrew"}:
        return "dns"
    if status == "Finished" or status.startswith("+"):
        return "classified"
    classified = row.get("ClassifiedPosition")
    if (
        isinstance(classified, (int, float))
        and classified == classified
        and classified > 0
    ):
        return "classified"
    if status:
        return "dnf"
    return "dnf"


def _named(sessions: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [row for row in sessions if row.get("session_name") == name]
    if not matches:
        return None
    return matches[-1]


def _records(table: Any) -> list[dict[str, Any]]:
    if table is None:
        return []
    if isinstance(table, list):
        return table
    to_dict = getattr(table, "to_dict", None)
    if callable(to_dict):
        return list(to_dict(orient="records"))
    raise HistoricalSourceError("A post-session table could not be read.")


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _retry(fn: Callable[[], Any], sleep: Callable[[float], None]) -> Any:
    delays = iter(_RETRY_DELAYS)
    while True:
        try:
            return fn()
        except HistoricalSourceError as exc:
            if "HTTP 429" not in str(exc):
                raise
            try:
                delay = next(delays)
            except StopIteration:
                raise exc from None
            sleep(delay)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
