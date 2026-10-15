"""HTTP transport for historical JSON. Redirects are refused."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from historical.errors import HistoricalSourceError

_REDIRECTS = {301, 302, 303, 307, 308}


class HttpxTransport:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        min_interval_sec: float = 0.34,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=False)
        self._min_interval = min_interval_sec
        self._sleep = sleep
        self._clock = clock
        self._last_at: float | None = None

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> Any:
        now = self._clock()
        if self._last_at is not None:
            wait = self._min_interval - (now - self._last_at)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_at = now
        response = self._client.get(url, params=params, headers=headers)
        if response.status_code in _REDIRECTS:
            raise HistoricalSourceError(f"Refused a redirect from {url}")
        if response.status_code != 200:
            raise HistoricalSourceError(
                f"Historical source returned HTTP {response.status_code} for {url}"
            )
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise HistoricalSourceError(
                f"Historical source did not return JSON for {url}"
            ) from exc
