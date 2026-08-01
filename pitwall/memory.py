"""Append-only, local session history with no hidden profile memory."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_HISTORY_READ_BYTES = 1024 * 1024
MAX_HISTORY_FILE_BYTES = 5 * 1024 * 1024
HISTORY_RETAIN_BYTES = 1024 * 1024
MAX_HISTORY_CONTENT_CHARS = 20_000


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
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        _compact_history(self.path)
        stored_content = content
        if len(stored_content) > MAX_HISTORY_CONTENT_CHARS:
            stored_content = (
                stored_content[:MAX_HISTORY_CONTENT_CHARS]
                + "\n[history entry truncated]"
            )
        entry = HistoryEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id[:200],
            role=role[:40],
            content=stored_content,
            used_tools=tuple(used_tools),
        )
        payload = asdict(entry)
        payload["used_tools"] = list(entry.used_tools)
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            return

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        requested = max(min(limit, 100), 1)
        try:
            lines = _bounded_tail_lines(self.path, MAX_HISTORY_READ_BYTES)
        except OSError:
            return []
        entries: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                candidate = json.loads(line)
            except (json.JSONDecodeError, RecursionError, ValueError):
                continue
            if not _is_history_entry(candidate):
                continue
            entries.append(candidate)
            if len(entries) >= requested:
                break
        entries.reverse()
        return entries


def _bounded_tail_lines(path: Path, byte_limit: int) -> list[str]:
    size = path.stat().st_size
    start = max(size - max(byte_limit, 1), 0)
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(max(byte_limit, 1))
    if start:
        newline = data.find(b"\n")
        data = b"" if newline < 0 else data[newline + 1 :]
    return data.decode("utf-8", errors="replace").splitlines()


def _compact_history(path: Path) -> None:
    """Keep recent local turns while placing a hard bound on disk growth."""
    try:
        if not path.exists() or path.stat().st_size <= MAX_HISTORY_FILE_BYTES:
            return
        lines = _bounded_tail_lines(path, HISTORY_RETAIN_BYTES)
        retained = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(retained)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise
    except OSError:
        # History is optional. A read-only/full disk must not break race planning.
        return


def _is_history_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key in ("timestamp", "session_id", "role", "content"):
        if not isinstance(value.get(key), str):
            return False
    used_tools = value.get("used_tools", [])
    return isinstance(used_tools, list) and all(
        isinstance(tool, str) for tool in used_tools
    )
