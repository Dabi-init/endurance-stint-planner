"""Small, explicit configuration for the local Pitwall workspace."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_CONFIG_BYTES = 256 * 1024


@dataclass(frozen=True)
class Settings:
    """User-controlled settings; no secrets or cloud telemetry are stored."""

    provider: str = "none"
    model: str = ""
    ollama_host: str = DEFAULT_OLLAMA_HOST
    remember_sessions: bool = True

    @property
    def model_enabled(self) -> bool:
        return self.provider == "ollama" and bool(self.model.strip())

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.provider not in {"none", "ollama"}:
            issues.append("provider must be 'none' or 'ollama'")
        try:
            parsed = urlparse(self.ollama_host)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError:
            return [*issues, "ollama_host is not a valid local URL"]
        if parsed.scheme not in {"http", "https"}:
            issues.append("ollama_host must use http:// or https://")
        if hostname not in ALLOWED_LOCAL_HOSTS:
            issues.append("ollama_host must point to this computer")
        if parsed.path not in {"", "/"}:
            issues.append("ollama_host cannot contain a path")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            issues.append(
                "ollama_host cannot contain credentials, a query, or a fragment"
            )
        return issues

    def to_toml(self) -> str:
        return "\n".join(
            [
                "# Pitwall Agent configuration",
                f'provider = "{_escape(self.provider)}"',
                f'model = "{_escape(self.model)}"',
                f'ollama_host = "{_escape(self.ollama_host.rstrip("/"))}"',
                f"remember_sessions = {str(self.remember_sessions).lower()}",
                "",
            ]
        )

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("config.toml is larger than the 256 KiB limit")
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError, RecursionError) as exc:
            raise ValueError(
                "config.toml is unreadable or invalid; repair it or move it aside "
                "and run 'pitwall init'"
            ) from exc
        return cls(
            provider=_text_setting(data, "provider", "none").strip().lower(),
            model=_text_setting(data, "model", "").strip(),
            ollama_host=_text_setting(data, "ollama_host", DEFAULT_OLLAMA_HOST).rstrip(
                "/"
            ),
            remember_sessions=_bool_setting(data, "remember_sessions", True),
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _text_setting(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"config.toml setting {key!r} must be text")
    return value


def _bool_setting(data: dict[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"config.toml setting {key!r} must be true or false")
    return value
