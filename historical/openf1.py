"""OpenF1 historical reads. Live timing is a separate paid product and is not called."""

from __future__ import annotations

from typing import Any

from historical.errors import HistoricalSourceError
from historical.terms import USER_AGENT

HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


class OpenF1Client:
    def __init__(
        self,
        transport: Any,
        *,
        base_url: str = "https://api.openf1.org/v1",
    ) -> None:
        self.transport = transport
        self.base_url = base_url.rstrip("/")

    def meetings(self, year: int) -> list[dict[str, Any]]:
        return self._get("/meetings", {"year": str(year)})

    def race_session(self, meeting_key: int) -> dict[str, Any]:
        rows = self._get(
            "/sessions",
            {"meeting_key": str(meeting_key), "session_name": "Race"},
        )
        if not rows:
            raise HistoricalSourceError(
                f"OpenF1 has no race session for meeting {meeting_key}."
            )
        return rows[0]

    def drivers(self, session_key: int) -> list[dict[str, Any]]:
        return self._get("/drivers", {"session_key": str(session_key)})

    def stints(self, session_key: int, driver_number: int) -> list[dict[str, Any]]:
        return self._get(
            "/stints",
            {"session_key": str(session_key), "driver_number": str(driver_number)},
        )

    def team_radio(self, session_key: int, driver_number: int) -> list[dict[str, Any]]:
        """Metadata only. ``recording_url`` is a link. This does not download audio."""
        return self._get(
            "/team_radio",
            {"session_key": str(session_key), "driver_number": str(driver_number)},
        )

    def _get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        payload = self.transport.get_json(f"{self.base_url}{path}", params, HEADERS)
        if isinstance(payload, dict):
            detail = payload.get("detail") or "OpenF1 returned an unexpected payload."
            raise HistoricalSourceError(str(detail))
        if not isinstance(payload, list):
            raise HistoricalSourceError(
                f"OpenF1 returned an unexpected payload for {path}."
            )
        return payload
