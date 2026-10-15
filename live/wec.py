"""Optional personal-use read of the public WEC timing page.

When the caller turns it on, this adapter fetches the public JSON at
https://insights.griiip.com/ that livetiming.fiawec.com shows. It keeps the
classification columns, holds one in-memory copy for a few seconds, and does
not write the feed to disk. It does not capture video, broadcast audio, or
car locations. This project does not have a commercial licence for that feed.
"""

from __future__ import annotations

import copy
import json
import time
from typing import Any, Protocol

import httpx

from live.sources import LiveSourceError

WEC_PAGE = "https://livetiming.fiawec.com/"
WEC_SERIES_ID = 10
_HOST = "https://insights.griiip.com/"
_LIST_URL = f"{_HOST}live/session-info/"
WEC_NOTICE = (
    "Optional personal-use read. When enabled, this adapter fetches the public "
    "JSON at https://insights.griiip.com/ for the timing page livetiming.fiawec.com. "
    "Pitwall does not store or redistribute that feed, and it does not capture "
    "video or broadcast audio. This project does not have a commercial licence "
    "for that feed. Leave this off unless you are using it for yourself."
)
_CACHE_TTL_SEC = 15.0
_cached: tuple[float, dict[str, Any]] | None = None
_USER_AGENT = (
    "pitwall-agent personal-use timing read (not stored, not redistributed; "
    "+https://github.com/Dabi-init/endurance-stint-planner)"
)


class WecTransport(Protocol):
    def get_json(self, url: str, params: dict[str, str]) -> Any:
        """Return one public JSON document. Must not write it to disk."""


class PublicWecTransport:
    """HTTP reader for the public timing host. It does not cache responses."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_json(self, url: str, params: dict[str, str]) -> Any:
        if not url.startswith(_HOST):
            raise LiveSourceError(
                "The timing adapter only reads the public WEC timing host."
            )
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=15.0, follow_redirects=False)
        try:
            response = client.get(
                url,
                params=params,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                raise LiveSourceError("Refused a redirect from the public timing host.")
            if response.status_code != 200:
                raise LiveSourceError(
                    "The public timing page did not return a timing table. Nothing was stored."
                )
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise LiveSourceError(
                    "The public timing page did not return JSON. Nothing was stored."
                ) from exc
        finally:
            if owns_client:
                client.close()


def clear_wec_cache() -> None:
    """Drop the in-memory timing copy. Nothing is written to disk."""
    global _cached
    _cached = None


def read_wec(
    *,
    enabled: bool,
    transport: WecTransport | None = None,
    now: float | None = None,
    cache: bool | None = None,
) -> dict[str, Any]:
    """Read the public WEC classification, or return the notice when disabled.

    A second enabled read inside ``_CACHE_TTL_SEC`` returns the in-memory copy
    and does not call the transport. Injected transports skip that cache unless
    ``cache`` is set.
    """
    payload: dict[str, Any] = {
        "enabled": bool(enabled),
        "fetched": False,
        "cached": False,
        "live": False,
        "page": WEC_PAGE,
        "notice": WEC_NOTICE,
        "session": None,
        "rows": [],
        "stored": False,
        "audio": "not captured",
        "video": "not captured",
    }
    if not enabled:
        return payload
    use_cache = (transport is None) if cache is None else cache
    clock = time.monotonic() if now is None else now
    global _cached
    if use_cache and _cached is not None and clock - _cached[0] < _CACHE_TTL_SEC:
        hit = copy.deepcopy(_cached[1])
        hit["cached"] = True
        return hit
    reader = transport or PublicWecTransport()
    listed = _read(reader, _LIST_URL, {"includeViewers": "false"})
    if not isinstance(listed, list):
        raise LiveSourceError(
            "The public timing page did not return a session list. Nothing was stored."
        )
    payload["fetched"] = True
    chosen = choose_wec_session(listed)
    if chosen is None:
        payload["notice"] = (
            f"{WEC_NOTICE} No FIA WEC session is on the public timing page right now."
        )
        if use_cache:
            _cached = (clock, copy.deepcopy(payload))
        return payload
    sid = session_id(chosen)
    snapshot = _read(reader, bootstrap_url(sid), {})
    if not isinstance(snapshot, dict):
        raise LiveSourceError(
            "The public timing page did not return a timing table. Nothing was stored."
        )
    payload["live"] = True
    payload["session"] = {
        "sid": sid,
        "series": "WEC",
        "event": _text(chosen.get("eventName")),
        "name": _text(chosen.get("sessionName")),
    }
    payload["rows"] = project_timing(snapshot, session=chosen)
    if use_cache:
        _cached = (clock, copy.deepcopy(payload))
    return payload


def choose_wec_session(rows: list[Any]) -> dict[str, Any] | None:
    """Pick one visible FIA WEC session. Other series are ignored."""
    visible: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("seriesId") != WEC_SERIES_ID:
            continue
        if row.get("hideFromUsers") is True:
            continue
        visible.append(row)
    races = [row for row in visible if row.get("isRaceSession") is True]
    pool = races or visible
    started = [row for row in pool if row.get("isStarted") is True]
    pool = started or pool
    if not pool:
        return None
    return max(pool, key=lambda row: str(row.get("startTime") or ""))


def session_id(row: dict[str, Any]) -> int:
    sid = row.get("sid")
    if isinstance(sid, bool) or not isinstance(sid, int) or not 0 < sid <= 10_000_000:
        raise LiveSourceError(
            "The public timing page did not name a session this adapter can read."
        )
    return sid


def bootstrap_url(sid: int) -> str:
    """Build the public snapshot URL from a checked session id."""
    checked = sid if isinstance(sid, int) and not isinstance(sid, bool) else 0
    if not 0 < checked <= 10_000_000:
        raise LiveSourceError(
            "The public timing page did not name a session this adapter can read."
        )
    return f"{_HOST}api/v2/public/live/session/{checked}/bootstrap"


def project_timing(
    snapshot: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep position, car, class, lap, gap, and team. Drop locations and audio."""
    ranks = snapshot.get("ranks")
    if not isinstance(ranks, list):
        return []
    gaps = _index(snapshot.get("gaps"))
    laps = _latest_laps(snapshot.get("laps"))
    teams = _teams(snapshot.get("participants"))
    classes = _class_names(snapshot, session)
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        (
            row
            for row in ranks
            if isinstance(row, dict) and row.get("isDeleted") is not True
        ),
        key=lambda row: (
            row.get("position") is None,
            row.get("position") if isinstance(row.get("position"), int) else 10**9,
        ),
    )
    for rank in ordered[:60]:
        pid = str(rank.get("pid") or "")
        car = _text(rank.get("carNumber")) or "—"
        gap = gaps.get(pid) or {}
        class_id = str(rank.get("classId") or "")
        rows.append(
            {
                "position": rank.get("position")
                if isinstance(rank.get("position"), int)
                else None,
                "car": car,
                "class_name": classes.get(class_id) or _short_class(class_id),
                "lap": laps.get(pid),
                "gap": _gap_text(gap),
                "team": teams.get(pid, ""),
            }
        )
    return rows


def _read(reader: WecTransport, url: str, params: dict[str, str]) -> Any:
    try:
        return reader.get_json(url, params)
    except LiveSourceError:
        raise
    except Exception as exc:
        raise LiveSourceError(
            "The public timing page could not be read. Nothing was stored."
        ) from exc


def _index(rows: Any) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if isinstance(row, dict) and row.get("pid") is not None:
            found[str(row["pid"])] = row
    return found


def _latest_laps(rows: Any) -> dict[str, int]:
    found: dict[str, int] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if not isinstance(row, dict) or row.get("pid") is None:
            continue
        lap = row.get("lapNumber")
        if not isinstance(lap, int):
            continue
        key = str(row["pid"])
        found[key] = max(found.get(key, 0), lap)
    return found


def _teams(rows: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    if not isinstance(rows, list):
        return found
    for row in rows:
        if isinstance(row, dict) and row.get("pid") is not None:
            found[str(row["pid"])] = _text(row.get("teamName"))
    return found


def _class_names(
    snapshot: dict[str, Any], session: dict[str, Any] | None
) -> dict[str, str]:
    names: dict[str, str] = {}
    info = (
        snapshot.get("sessionInfo")
        if isinstance(snapshot.get("sessionInfo"), dict)
        else {}
    )
    blobs: list[Any] = []
    if isinstance(info, dict):
        blobs.append(info.get("sessionClasses"))
    if session is not None:
        blobs.append(session.get("sessionClasses"))
    for blob in blobs:
        if not isinstance(blob, list):
            continue
        for row in blob:
            if not isinstance(row, dict):
                continue
            key = str(row.get("classId") or row.get("id") or "")
            label = _text(row.get("className") or row.get("name"))
            if key and label:
                names[key] = label
    return names


def _short_class(class_id: str) -> str:
    if class_id and len(class_id) <= 24 and "-" not in class_id:
        return class_id
    return "Class"


def _gap_text(gap: dict[str, Any]) -> str:
    laps = gap.get("gapToFirstLaps")
    millis = gap.get("gapToFirstMillis")
    if isinstance(laps, int) and laps > 0:
        noun = "lap" if laps == 1 else "laps"
        return f"+{laps} {noun}"
    if isinstance(millis, int) and millis > 0:
        return f"+{millis / 1000:.3f} s"
    if millis == 0 or laps == 0:
        return "leader"
    return "—"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
