"""Workspace boundaries and recoverable local persistence."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall.config import Settings


class WorkspaceError(ValueError):
    """Raised when a requested file would escape the Pitwall workspace."""


@dataclass(frozen=True)
class PitwallWorkspace:
    """A race project stored in one visible ``.pitwall`` directory."""

    root: Path

    @classmethod
    def from_path(cls, path: Path | str | None = None) -> PitwallWorkspace:
        candidate = Path(path) if path is not None else Path.cwd() / ".pitwall"
        return cls(candidate.expanduser().resolve())

    @property
    def config_path(self) -> Path:
        return self.root / "config.toml"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def race_path(self) -> Path:
        return self.root / "race.json"

    @property
    def memory_path(self) -> Path:
        return self.root / "history.jsonl"

    def initialise(self) -> bool:
        """Create the workspace without overwriting existing user configuration."""
        created = not self.root.exists()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(Settings().to_toml(), encoding="utf-8")
        if not self.state_path.exists():
            self.write_state(
                {"active_telemetry": None, "active_preset": "6h Endurance"}
            )
        return created

    def settings(self) -> Settings:
        return Settings.load(self.config_path)

    def save_settings(self, settings: Settings) -> None:
        issues = settings.validate()
        if issues:
            raise WorkspaceError("; ".join(issues))
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(settings.to_toml(), encoding="utf-8")

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"active_telemetry": None, "active_preset": "6h Endurance"}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"active_telemetry": None, "active_preset": "6h Endurance"}

    def write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def race_data(self) -> dict[str, Any]:
        if not self.race_path.exists():
            raise WorkspaceError(
                "No current race exists. Run 'pitwall race init' first."
            )
        try:
            payload = json.loads(self.race_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WorkspaceError("race.json contains invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WorkspaceError("race.json must contain one JSON object")
        return payload

    def save_race(self, data: dict[str, Any], *, overwrite: bool = False) -> Path:
        self.initialise()
        if self.race_path.exists() and not overwrite:
            raise WorkspaceError(
                "A current race already exists. Use --replace only if intentional."
            )
        self.race_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        state = self.state()
        state["active_preset"] = "Current Race"
        self.write_state(state)
        return self.race_path

    def ingest(self, source: Path, *, name: str | None = None) -> Path:
        """Copy telemetry into the project so model tools cannot read arbitrary files."""
        source = source.expanduser().resolve()
        if not source.is_file():
            raise WorkspaceError(f"Telemetry file does not exist: {source}")
        if source.suffix.lower() != ".csv":
            raise WorkspaceError("Telemetry must be a .csv file")
        self.initialise()
        safe_name = _safe_filename(name or source.name, suffix=".csv")
        target = self.data_dir / safe_name
        if target.exists():
            raise WorkspaceError(
                f"{safe_name} already exists; rename the source or remove it explicitly"
            )
        shutil.copy2(source, target)
        state = self.state()
        state["active_telemetry"] = safe_name
        self.write_state(state)
        return target

    def data_file(self, name: str | None = None) -> Path:
        selected = name or self.state().get("active_telemetry")
        if not selected:
            raise WorkspaceError(
                "No telemetry is active. Run 'pitwall ingest FILE.csv'."
            )
        safe_name = _safe_filename(str(selected), suffix=".csv")
        target = (self.data_dir / safe_name).resolve()
        if target.parent != self.data_dir.resolve() or not target.is_file():
            raise WorkspaceError(
                f"Telemetry is not in this Pitwall workspace: {safe_name}"
            )
        return target

    def report_file(self, name: str, *, suffix: str = ".md") -> Path:
        self.initialise()
        safe_name = _safe_filename(name, suffix=suffix)
        target = (self.reports_dir / safe_name).resolve()
        if target.parent != self.reports_dir.resolve():
            raise WorkspaceError("Report path escapes the Pitwall workspace")
        return target

    def new_report_file(self, name: str, *, suffix: str = ".md") -> Path:
        """Resolve a report path that must not already exist.

        Non-overwrite protection belongs to the workspace layer so that every
        caller - CLI, agent tool, or library user - gets the same guarantee.
        """
        target = self.report_file(name, suffix=suffix)
        if target.exists():
            raise WorkspaceError(
                f"{target.name} already exists; choose a new report name"
            )
        return target

    def new_validation_file(self, name: str, *, suffix: str = ".md") -> Path:
        """Resolve a not-yet-existing validation report inside the workspace root."""
        self.initialise()
        safe_name = _safe_filename(name, suffix=suffix)
        target = (self.root / safe_name).resolve()
        if target.parent != self.root.resolve():
            raise WorkspaceError("Validation path escapes the Pitwall workspace")
        if target.exists():
            raise WorkspaceError(
                f"{target.name} already exists; choose a new report name"
            )
        return target


def _safe_filename(value: str, *, suffix: str) -> str:
    candidate = Path(value).name
    stem = Path(candidate).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_")
    if not cleaned:
        raise WorkspaceError("A safe file name is required")
    return cleaned[:80] + suffix
