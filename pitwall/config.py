"""Small, explicit configuration for the local Pitwall workspace."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


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
        parsed = urlparse(self.ollama_host)
        if parsed.scheme not in {"http", "https"}:
            issues.append("ollama_host must use http:// or https://")
        if parsed.hostname not in ALLOWED_LOCAL_HOSTS:
            issues.append("ollama_host must point to this computer")
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
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return cls(
            provider=str(data.get("provider", "none")).strip().lower(),
            model=str(data.get("model", "")).strip(),
            ollama_host=str(data.get("ollama_host", DEFAULT_OLLAMA_HOST)).rstrip("/"),
            remember_sessions=bool(data.get("remember_sessions", True)),
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
