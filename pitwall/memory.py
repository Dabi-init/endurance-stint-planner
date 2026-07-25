"""Append-only, local session history with no hidden profile memory."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HistoryEntry:
    timestamp: str
    session_id: str
    role: str
    content: str
    used_tools: tuple[str, ...] = ()


class SessionHistory:
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        used_tools: list[str] | tuple[str, ...] = (),
    ) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = HistoryEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            role=role,
            content=content,
            used_tools=tuple(used_tools),
        )
        payload = asdict(entry)
        payload["used_tools"] = list(entry.used_tools)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        entries: list[dict[str, Any]] = []
        for line in lines[-max(min(limit, 100), 1) :]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
