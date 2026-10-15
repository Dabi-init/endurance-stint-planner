"""Jolpica-F1 (Ergast-shaped) reads. Callers must keep the CC BY-NC-SA note."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from historical.errors import HistoricalSourceError
from historical.terms import USER_AGENT

HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


class JolpicaClient:
    def __init__(
        self,
        transport: Any,
        *,
        base_url: str = "https://api.jolpi.ca/ergast/f1",
        page_size: int = 100,
    ) -> None:
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size

    def races(self, season: int) -> list[dict[str, Any]]:
        return self._paged(f"/{season}.json", _races)

    def results(self, season: int, round_: int) -> list[dict[str, Any]]:
        return self._paged(f"/{season}/{round_}/results.json", _results)

    def pitstops(self, season: int, round_: int) -> list[dict[str, Any]]:
        return self._paged(f"/{season}/{round_}/pitstops.json", _pitstops)

    def _paged(
        self,
        path: str,
        extract: Callable[[dict[str, Any]], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        offset = 0
        rows: list[dict[str, Any]] = []
        while True:
            payload = self.transport.get_json(
                f"{self.base_url}{path}",
                {"limit": str(self.page_size), "offset": str(offset)},
                HEADERS,
            )
            if not isinstance(payload, dict) or "MRData" not in payload:
                raise HistoricalSourceError(
                    f"Jolpica returned an unexpected payload for {path}."
                )
            total = int(payload["MRData"]["total"])
            chunk = extract(payload)
            rows.extend(chunk)
            offset += self.page_size
            if offset >= total or not chunk:
                break
            if offset > 10_000:
                raise HistoricalSourceError(
                    "Historical response exceeded the page cap."
                )
        return rows


def _races(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload["MRData"]["RaceTable"].get("Races", []))


def _first_race(payload: dict[str, Any]) -> dict[str, Any] | None:
    races = payload["MRData"]["RaceTable"].get("Races", [])
    if not races:
        return None
    return races[0]


def _results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    race = _first_race(payload)
    if race is None:
        return []
    return list(race.get("Results", []))


def _pitstops(payload: dict[str, Any]) -> list[dict[str, Any]]:
    race = _first_race(payload)
    if race is None:
        return []
    return list(race.get("PitStops", []))
