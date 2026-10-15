"""Local JSON cache. The directory is gitignored and holds no images."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


def cache_key(url: str, params: dict[str, str]) -> str:
    query = urlencode(sorted((key, str(value)) for key, value in params.items()))
    return f"{url}?{query}" if query else url


class FileCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload["value"]

    def put(self, key: str, value: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(
            json.dumps({"value": value}, separators=(",", ":")),
            encoding="utf-8",
        )


class CachingTransport:
    """Cache successful JSON reads. Failures are not stored."""

    def __init__(self, inner: Any, cache: FileCache) -> None:
        self.inner = inner
        self.cache = cache

    def get_json(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> Any:
        key = cache_key(url, params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        value = self.inner.get_json(url, params, headers)
        self.cache.put(key, value)
        return value
