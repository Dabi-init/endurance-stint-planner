"""Workspace boundaries and recoverable local persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, RLock
from typing import Any

if os.name == "nt":  # pragma: no cover - selected by the host platform
    import msvcrt
else:  # pragma: no cover - selected by the host platform
    import fcntl

from pitwall.config import Settings

MAX_TELEMETRY_BYTES = 10 * 1024 * 1024
MAX_DATA_DIRECTORY_BYTES = 100 * 1024 * 1024
MAX_CONTROL_FILE_BYTES = 1024 * 1024
MAX_JSON_NESTING = 100
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_DIRECTORY_BYTES = 25 * 1024 * 1024
MAX_ARTIFACT_FILES = 500
COPY_CHUNK_BYTES = 1024 * 1024
WORKSPACE_LOCK_NAME = ".workspace.lock"
_NON_ARTIFACT_ROOT_FILES = frozenset(
    {
        WORKSPACE_LOCK_NAME,
        "config.toml",
        "history.jsonl",
        "race.json",
        "state.json",
    }
)
_THREAD_LOCKS: dict[str, RLock] = {}
_THREAD_LOCKS_GUARD = Lock()
BUNDLED_SYNTHETIC_SHA256 = frozenset(
    {
        # Git checkout with CRLF conversion on Windows.
        "0f0e1727f5f79437722ee28c14587bbdcfca3af66e22f0d6bb6ecd59d1499b79",
        # Git blob / GitHub ZIP with LF line endings.
        "4cdaafdb0a9c81a0054aa2caf05fc44262b12b79305b2658d511dd7e8f26dd34",
    }
)


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
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.reports_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(
                f"Cannot initialise Pitwall workspace at {self.root}: {exc}"
            ) from exc
        self._child_directory(self.data_dir, "Telemetry data")
        self._child_directory(self.reports_dir, "Reports")
        if not self.config_path.exists():
            try:
                _write_text_exclusive(self.config_path, Settings().to_toml())
            except FileExistsError:
                pass
        if not self.state_path.exists():
            try:
                _write_text_exclusive(
                    self.state_path,
                    _json_document(_default_state(), "Workspace state"),
                )
            except FileExistsError:
                pass
        return created

    def _child_directory(self, directory: Path, label: str) -> Path:
        resolved = directory.resolve()
        if resolved.parent != self.root.resolve():
            raise WorkspaceError(f"{label} directory escapes the Pitwall workspace")
        return resolved

    def settings(self) -> Settings:
        return Settings.load(self.config_path)

    def save_settings(self, settings: Settings) -> None:
        issues = settings.validate()
        if issues:
            raise WorkspaceError("; ".join(issues))
        self.root.mkdir(parents=True, exist_ok=True)
        with _workspace_lock(self.root):
            _write_text_atomic(self.config_path, settings.to_toml())

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _default_state()
        try:
            if self.state_path.stat().st_size > MAX_CONTROL_FILE_BYTES:
                return _default_state()
            payload = _json_loads_strict(self.state_path.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError, OSError, RecursionError):
            return _default_state()
        return payload if isinstance(payload, dict) else _default_state()

    def write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with _workspace_lock(self.root):
            self._write_state_unlocked(state)

    def _write_state_unlocked(self, state: dict[str, Any]) -> None:
        text = _json_document(state, "Workspace state")
        _write_text_atomic(self.state_path, text)

    def race_data(self) -> dict[str, Any]:
        if not self.race_path.exists():
            raise WorkspaceError(
                "No current race exists. Run 'pitwall race init' first."
            )
        try:
            if self.race_path.stat().st_size > MAX_CONTROL_FILE_BYTES:
                raise WorkspaceError(
                    "race.json is larger than the 1 MiB control-file limit"
                )
            payload = _json_loads_strict(self.race_path.read_text(encoding="utf-8"))
        except WorkspaceError:
            raise
        except (UnicodeError, ValueError, OSError, RecursionError) as exc:
            raise WorkspaceError(f"race.json cannot be read: {exc}") from exc
        if not isinstance(payload, dict):
            raise WorkspaceError("race.json must contain one JSON object")
        return payload

    def save_race(self, data: dict[str, Any], *, overwrite: bool = False) -> Path:
        text = _json_document(data, "Race configuration", ensure_ascii=False)
        self.initialise()
        with _workspace_lock(self.root):
            if overwrite:
                _write_text_atomic(self.race_path, text)
            else:
                try:
                    _write_text_exclusive(self.race_path, text)
                except FileExistsError as exc:
                    raise WorkspaceError(
                        "A current race already exists. Use --replace only if intentional."
                    ) from exc
            state = self.state()
            state["active_preset"] = "Current Race"
            self._write_state_unlocked(state)
        return self.race_path

    def ingest(self, source: Path, *, name: str | None = None) -> Path:
        """Copy telemetry into the project so model tools cannot read arbitrary files."""
        source = source.expanduser().resolve()
        if not source.is_file():
            raise WorkspaceError(f"Telemetry file does not exist: {source}")
        if source.suffix.lower() != ".csv":
            raise WorkspaceError("Telemetry must be a .csv file")
        try:
            source_size = source.stat().st_size
        except OSError as exc:
            raise WorkspaceError(f"Cannot inspect telemetry file: {exc}") from exc
        if source_size > MAX_TELEMETRY_BYTES:
            raise WorkspaceError(
                "Telemetry file is too large: "
                f"{source_size / (1024 * 1024):.1f} MiB; "
                f"maximum {MAX_TELEMETRY_BYTES // (1024 * 1024)} MiB"
            )
        self.initialise()
        safe_name = _safe_filename(name or source.name, suffix=".csv")
        target = self._child_directory(self.data_dir, "Telemetry data") / safe_name
        with _workspace_lock(self.root):
            try:
                current_data_bytes = sum(
                    item.stat().st_size
                    for item in self.data_dir.iterdir()
                    if item.is_file()
                )
            except OSError as exc:
                raise WorkspaceError(
                    f"Cannot measure the telemetry directory: {exc}"
                ) from exc
            if current_data_bytes + source_size > MAX_DATA_DIRECTORY_BYTES:
                raise WorkspaceError(
                    "Telemetry workspace quota exceeded: keep the data directory below "
                    f"{MAX_DATA_DIRECTORY_BYTES // (1024 * 1024)} MiB"
                )
            try:
                source_sha256 = _copy_file_exclusive(
                    source,
                    target,
                    MAX_TELEMETRY_BYTES,
                )
            except FileExistsError as exc:
                raise WorkspaceError(
                    f"{safe_name} already exists; rename the source or remove it "
                    "explicitly"
                ) from exc
            except (OSError, WorkspaceError) as exc:
                raise WorkspaceError(f"Cannot import telemetry: {exc}") from exc
            try:
                copied_data_bytes = sum(
                    item.stat().st_size
                    for item in self.data_dir.iterdir()
                    if item.is_file()
                )
            except OSError as exc:
                target.unlink(missing_ok=True)
                raise WorkspaceError(
                    f"Cannot verify telemetry storage after import: {exc}"
                ) from exc
            if copied_data_bytes > MAX_DATA_DIRECTORY_BYTES:
                target.unlink(missing_ok=True)
                raise WorkspaceError(
                    "Telemetry grew during import and would exceed the workspace "
                    f"quota of {MAX_DATA_DIRECTORY_BYTES // (1024 * 1024)} MiB"
                )
            state = self.state()
            state["active_telemetry"] = safe_name
            sources = state.get("telemetry_sources")
            if not isinstance(sources, dict):
                sources = {}
            sources[safe_name] = {
                "original_name": source.name,
                "sha256": source_sha256,
                "synthetic": (
                    "synthetic" in source.name.lower()
                    or source_sha256 in BUNDLED_SYNTHETIC_SHA256
                ),
            }
            state["telemetry_sources"] = sources
            try:
                self._write_state_unlocked(state)
            except (OSError, WorkspaceError) as exc:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                raise WorkspaceError(
                    f"Telemetry was copied but could not be activated: {exc}"
                ) from exc
        return target

    def data_file(self, name: str | None = None) -> Path:
        selected = name or self.state().get("active_telemetry")
        if not selected:
            raise WorkspaceError(
                "No telemetry is active. Run 'pitwall ingest FILE.csv'."
            )
        safe_name = _safe_filename(str(selected), suffix=".csv")
        data_directory = self._child_directory(self.data_dir, "Telemetry data")
        target = (data_directory / safe_name).resolve()
        if target.parent != data_directory or not target.is_file():
            raise WorkspaceError(
                f"Telemetry is not in this Pitwall workspace: {safe_name}"
            )
        try:
            if target.stat().st_size > MAX_TELEMETRY_BYTES:
                raise WorkspaceError(
                    f"Telemetry exceeds the {MAX_TELEMETRY_BYTES // (1024 * 1024)} "
                    "MiB read limit"
                )
        except OSError as exc:
            raise WorkspaceError(f"Cannot inspect telemetry file: {exc}") from exc
        return target

    def telemetry_is_synthetic(self, name: str) -> bool:
        safe_name = _safe_filename(name, suffix=".csv")
        sources = self.state().get("telemetry_sources")
        if isinstance(sources, dict):
            provenance = sources.get(safe_name)
            if isinstance(provenance, dict) and provenance.get("synthetic") is True:
                return True
        if "synthetic" in safe_name.lower():
            return True
        try:
            path = self.data_file(safe_name)
            return _sha256_file(path) in BUNDLED_SYNTHETIC_SHA256
        except (OSError, WorkspaceError):
            return False

    def report_file(self, name: str, *, suffix: str = ".md") -> Path:
        self.initialise()
        safe_name = _safe_filename(name, suffix=suffix)
        reports_directory = self._child_directory(self.reports_dir, "Reports")
        target = (reports_directory / safe_name).resolve()
        if target.parent != reports_directory:
            raise WorkspaceError("Report path escapes the Pitwall workspace")
        return target

    def new_report_file(self, name: str, *, suffix: str = ".md") -> Path:
        """Resolve a report path that must not already exist.

        Non-overwrite protection belongs to the workspace layer so that every
        caller - CLI, agent tool, or library user - gets the same guarantee.
        """
        target = self.report_file(name, suffix=suffix)
        return self._write_new_artifact(target, "")

    def write_new_report(
        self,
        name: str,
        content: str,
        *,
        suffix: str = ".md",
    ) -> Path:
        """Create and fully write a report with operating-system exclusivity."""
        target = self.report_file(name, suffix=suffix)
        return self._write_new_artifact(target, content)

    def new_validation_file(self, name: str, *, suffix: str = ".md") -> Path:
        """Resolve a not-yet-existing validation report inside the workspace root."""
        self.initialise()
        safe_name = _safe_filename(name, suffix=suffix)
        target = (self.root / safe_name).resolve()
        if target.parent != self.root.resolve():
            raise WorkspaceError("Validation path escapes the Pitwall workspace")
        return self._write_new_artifact(target, "")

    def write_new_validation(
        self,
        name: str,
        content: str,
        *,
        suffix: str = ".md",
    ) -> Path:
        """Create a complete validation report without an overwrite race."""
        self.initialise()
        safe_name = _safe_filename(name, suffix=suffix)
        target = (self.root / safe_name).resolve()
        if target.parent != self.root.resolve():
            raise WorkspaceError("Validation path escapes the Pitwall workspace")
        return self._write_new_artifact(target, content)

    def _write_new_artifact(self, target: Path, content: str) -> Path:
        try:
            content_bytes = len(content.encode("utf-8"))
        except (AttributeError, UnicodeError) as exc:
            raise WorkspaceError("Report content must be valid UTF-8 text") from exc
        if content_bytes > MAX_ARTIFACT_BYTES:
            raise WorkspaceError(
                "Report is too large: "
                f"maximum {MAX_ARTIFACT_BYTES // (1024 * 1024)} MiB"
            )
        with _workspace_lock(self.root):
            if target.exists():
                raise WorkspaceError(
                    f"{target.name} already exists; choose a new report name"
                )
            artifact_count, artifact_bytes = _artifact_usage(self)
            if artifact_count >= MAX_ARTIFACT_FILES:
                raise WorkspaceError(
                    f"Report file limit reached: maximum {MAX_ARTIFACT_FILES} files"
                )
            if artifact_bytes + content_bytes > MAX_ARTIFACT_DIRECTORY_BYTES:
                raise WorkspaceError(
                    "Report storage quota exceeded: keep reports and validations below "
                    f"{MAX_ARTIFACT_DIRECTORY_BYTES // (1024 * 1024)} MiB"
                )
            try:
                _write_text_exclusive(target, content)
            except FileExistsError as exc:
                raise WorkspaceError(
                    f"{target.name} already exists; choose a new report name"
                ) from exc
        return target


def _safe_filename(value: str, *, suffix: str) -> str:
    candidate = Path(value).name
    stem = Path(candidate).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_")
    if not cleaned:
        raise WorkspaceError("A safe file name is required")
    return cleaned[:80] + suffix


def _default_state() -> dict[str, Any]:
    return {
        "active_telemetry": None,
        "active_preset": "6h Endurance",
        "telemetry_sources": {},
    }


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite number {value!r} is not valid")


def _json_loads_strict(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_json_constant)


def _json_document(
    payload: dict[str, Any],
    label: str,
    *,
    ensure_ascii: bool = True,
) -> str:
    if not isinstance(payload, dict):
        raise WorkspaceError(f"{label} must be one JSON object")
    _validate_json_nesting(payload, label)
    try:
        document = (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=ensure_ascii,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkspaceError(f"{label} contains an unsupported value: {exc}") from exc
    if len(document.encode("utf-8")) > MAX_CONTROL_FILE_BYTES:
        raise WorkspaceError(
            f"{label} exceeds the {MAX_CONTROL_FILE_BYTES // (1024 * 1024)} MiB "
            "control-file limit"
        )
    return document


def _validate_json_nesting(payload: dict[str, Any], label: str) -> None:
    stack: list[tuple[Any, int]] = [(payload, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_JSON_NESTING:
            raise WorkspaceError(
                f"{label} contains an unsupported value: JSON nesting exceeds "
                f"{MAX_JSON_NESTING} levels"
            )
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, (list, tuple)):
            stack.extend((child, depth + 1) for child in value)


def _thread_lock(root: Path) -> RLock:
    key = os.path.normcase(str(root.resolve()))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, RLock())


@contextmanager
def _workspace_lock(root: Path) -> Iterator[None]:
    """Serialize workspace mutations in this process and across local processes."""
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspaceError(f"Cannot create workspace lock directory: {exc}") from exc

    with _thread_lock(root):
        lock_path = root / WORKSPACE_LOCK_NAME
        try:
            handle = lock_path.open("a+b")
        except OSError as exc:
            raise WorkspaceError(f"Cannot open Pitwall workspace lock: {exc}") from exc
        with handle:
            try:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise WorkspaceError(f"Cannot lock Pitwall workspace: {exc}") from exc
            body_failed = False
            try:
                yield
            except BaseException:
                body_failed = True
                raise
            finally:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError as exc:
                    if not body_failed:
                        raise WorkspaceError(
                            f"Cannot unlock Pitwall workspace: {exc}"
                        ) from exc


def _artifact_usage(workspace: PitwallWorkspace) -> tuple[int, int]:
    """Return the count and bytes of app-created reports and validations."""
    try:
        report_files = [
            item for item in workspace.reports_dir.iterdir() if item.is_file()
        ]
        root_files = [
            item
            for item in workspace.root.iterdir()
            if item.is_file() and item.name not in _NON_ARTIFACT_ROOT_FILES
        ]
        artifacts = [*report_files, *root_files]
        return len(artifacts), sum(item.stat().st_size for item in artifacts)
    except OSError as exc:
        raise WorkspaceError(f"Cannot measure report storage: {exc}") from exc


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
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


def _write_text_exclusive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise


def _copy_file_exclusive(source: Path, target: Path, byte_limit: int) -> str:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    copied = 0
    digest = hashlib.sha256()
    try:
        with (
            source.open("rb") as source_handle,
            os.fdopen(descriptor, "wb") as target_handle,
        ):
            while chunk := source_handle.read(COPY_CHUNK_BYTES):
                copied += len(chunk)
                if copied > byte_limit:
                    raise WorkspaceError(
                        "Telemetry file grew beyond the allowed size while importing"
                    )
                digest.update(chunk)
                target_handle.write(chunk)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        shutil.copystat(source, target)
        return digest.hexdigest()
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        target.unlink(missing_ok=True)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
