"""Anonymise driver labels before a tool result enters model context.

Driver names come from telemetry CSVs and user configuration, which are
untrusted data. The deterministic engine keeps the real names for the human
crew; the language model only ever sees ``Driver_1``, ``Driver_2``, and so on.
"""

from __future__ import annotations

from typing import Any

DRIVER_VALUE_KEYS = ("Driver", "driver", "driver_name", "start_driver")
DRIVER_MAP_KEYS = (
    "driver_totals_min",
    "driver_pace_deltas_sec",
    "driver_totals",
    "driver_pace_deltas",
)

REDACTION_NOTICE = (
    "Driver names are replaced with Driver_1, Driver_2, ... in model context. "
    "The unmodified names remain in the deterministic output shown to the crew."
)


def _collect_names(node: Any, names: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in DRIVER_VALUE_KEYS and isinstance(value, str) and value.strip():
                if value not in names:
                    names.append(value)
            elif key in DRIVER_MAP_KEYS and isinstance(value, dict):
                for name in value:
                    if isinstance(name, str) and name.strip() and name not in names:
                        names.append(name)
            else:
                _collect_names(value, names)
    elif isinstance(node, list):
        for item in node:
            _collect_names(item, names)


def driver_alias_map(payload: Any) -> dict[str, str]:
    """Build a stable ``real name -> Driver_N`` map in first-seen order."""
    names: list[str] = []
    _collect_names(payload, names)
    return {name: f"Driver_{index}" for index, name in enumerate(names, start=1)}


def _apply(node: Any, aliases: dict[str, str]) -> Any:
    if isinstance(node, dict):
        return {
            aliases.get(key, key) if isinstance(key, str) else key: _apply(
                value, aliases
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_apply(item, aliases) for item in node]
    if isinstance(node, str):
        return _replace_in_text(node, aliases)
    return node


def _replace_in_text(text: str, aliases: dict[str, str]) -> str:
    """Replace whole names first so embedded mentions are scrubbed too."""
    if text in aliases:
        return aliases[text]
    result = text
    for name, alias in sorted(aliases.items(), key=lambda item: -len(item[0])):
        if len(name) >= 2 and name in result:
            result = result.replace(name, alias)
    return result


def anonymise_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a tool result with every driver label anonymised."""
    aliases = driver_alias_map(payload)
    if not aliases:
        return payload
    redacted = _apply(payload, aliases)
    redacted["driver_labels_redacted"] = REDACTION_NOTICE
    return redacted
