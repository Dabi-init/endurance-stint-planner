"""Regression tests for persistence and hostile local-input boundaries."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from multiprocessing import get_context
from pathlib import Path
from threading import Barrier, Event, Lock

import pytest

import engine.telemetry as telemetry_module
import pitwall.memory as memory_module
import pitwall.workspace as workspace_module
from engine.models import RaceConfig
from engine.planner import DEFAULT_PRESET, load_preset
from engine.telemetry import calibrate_telemetry
from pitwall.memory import SessionHistory
from pitwall.tools import build_registry
from pitwall.workspace import PitwallWorkspace, WorkspaceError

ROOT = Path(__file__).resolve().parent.parent


def _process_lock_probe(root: str, started: object, acquired: object) -> None:
    started.set()  # type: ignore[attr-defined]
    with workspace_module._workspace_lock(Path(root)):
        acquired.set()  # type: ignore[attr-defined]


@pytest.fixture
def workspace(tmp_path: Path) -> PitwallWorkspace:
    result = PitwallWorkspace.from_path(tmp_path / ".pitwall")
    result.initialise()
    return result


def test_missing_race_uses_an_explicitly_labelled_demo(
    workspace: PitwallWorkspace,
) -> None:
    result = build_registry(workspace).execute("compare_race_strategies")

    assert result.ok
    assert result.data["preset"] == f"{DEFAULT_PRESET} demo (no current race)"


@pytest.mark.parametrize("tool", ["plan_race", "compare_race_strategies"])
def test_existing_corrupt_race_fails_closed(
    workspace: PitwallWorkspace,
    tool: str,
) -> None:
    workspace.race_path.write_text('{"race_name":', encoding="utf-8")

    result = build_registry(workspace).execute(tool)

    assert not result.ok
    assert "race.json cannot be read" in result.error
    assert "demo" not in result.error.lower()


@pytest.mark.parametrize("tool", ["plan_race", "compare_race_strategies"])
def test_existing_structurally_invalid_race_fails_closed(
    workspace: PitwallWorkspace,
    tool: str,
) -> None:
    workspace.race_path.write_text('{"drivers": null}\n', encoding="utf-8")

    result = build_registry(workspace).execute(tool)

    assert not result.ok
    assert "drivers must be a JSON array" in result.error


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "race configuration must be a JSON object"),
        ({"drivers": None}, "drivers must be a JSON array"),
        ({"drivers": [[]]}, "drivers[0] must be a JSON object"),
        ({"regulations": None}, "regulations must be a JSON object"),
        ({"services_parallel": "false"}, "services_parallel must be a boolean"),
        (
            {"regulations": {"change_tyres_every_stop": "false"}},
            "regulations.change_tyres_every_stop must be a boolean",
        ),
        ({"base_lap_time_sec": float("inf")}, "must be a finite number"),
        ({"fuel_tank_liters": "100"}, "must be a finite number"),
        ({"tyre_life_laps": 28.0}, "tyre_life_laps must be an integer"),
    ],
)
def test_race_deserialization_rejects_ambiguous_or_nonfinite_types(
    payload: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message.replace("[", r"\[")):
        RaceConfig.from_dict(payload)  # type: ignore[arg-type]


def test_impossible_current_race_is_a_failed_tool_result(
    workspace: PitwallWorkspace,
) -> None:
    payload = load_preset(DEFAULT_PRESET).to_dict()
    payload["fuel_tank_liters"] = 10.0
    payload["fuel_consumption_per_lap"] = 20.0
    workspace.save_race(payload)
    registry = build_registry(workspace)

    plan = registry.execute("plan_race")
    comparison = registry.execute("compare_race_strategies")

    assert not plan.ok
    assert not comparison.ok
    assert "cannot produce a feasible plan" in plan.error
    assert "tank" in plan.error.lower()


def test_tiny_lap_time_is_rejected_before_planning(
    workspace: PitwallWorkspace,
) -> None:
    payload = load_preset(DEFAULT_PRESET).to_dict()
    payload["base_lap_time_sec"] = 0.001
    workspace.save_race(payload)

    result = build_registry(workspace).execute("plan_race")

    assert not result.ok
    assert "at least 20 seconds" in result.error


def test_nonfinite_race_save_preserves_the_existing_document(
    workspace: PitwallWorkspace,
) -> None:
    payload = load_preset(DEFAULT_PRESET).to_dict()
    workspace.save_race(payload)
    original = workspace.race_path.read_bytes()
    invalid = deepcopy(payload)
    invalid["base_lap_time_sec"] = float("nan")

    with pytest.raises(WorkspaceError, match="unsupported value"):
        workspace.save_race(invalid, overwrite=True)

    assert workspace.race_path.read_bytes() == original


def test_atomic_state_write_preserves_previous_file_when_replace_fails(
    workspace: PitwallWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = workspace.state_path.read_bytes()

    def fail_replace(source: object, target: object) -> None:
        raise OSError("simulated interrupted replacement")

    monkeypatch.setattr(workspace_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="interrupted replacement"):
        workspace.write_state({"active_preset": "Changed"})

    assert workspace.state_path.read_bytes() == original
    assert not list(workspace.root.glob(".state.json.*.tmp"))


def test_deeply_nested_state_serialization_is_a_controlled_error(
    workspace: PitwallWorkspace,
) -> None:
    original = workspace.state_path.read_bytes()
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(2_000):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child

    with pytest.raises(WorkspaceError, match="unsupported value"):
        workspace.write_state(nested)

    assert workspace.state_path.read_bytes() == original


def test_workspace_lock_blocks_another_process(workspace: PitwallWorkspace) -> None:
    context = get_context("spawn")
    started = context.Event()
    acquired = context.Event()
    process = context.Process(
        target=_process_lock_probe,
        args=(str(workspace.root), started, acquired),
    )
    try:
        with workspace_module._workspace_lock(workspace.root):
            process.start()
            assert started.wait(5)
            assert not acquired.wait(0.25)
        assert acquired.wait(5)
        process.join(5)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_report_creation_is_exclusive_under_concurrency(
    workspace: PitwallWorkspace,
) -> None:
    barrier = Barrier(2)

    def write_report(content: str) -> str:
        barrier.wait()
        try:
            workspace.write_new_report("same-name", content)
        except WorkspaceError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write_report, ("first", "second")))

    assert sorted(outcomes) == ["conflict", "created"]
    assert (workspace.reports_dir / "same-name.md").read_text(encoding="utf-8") in {
        "first",
        "second",
    }


def test_report_and_validation_growth_is_bounded(
    workspace: PitwallWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "MAX_ARTIFACT_BYTES", 8)
    monkeypatch.setattr(workspace_module, "MAX_ARTIFACT_DIRECTORY_BYTES", 10)
    monkeypatch.setattr(workspace_module, "MAX_ARTIFACT_FILES", 10)

    first = workspace.write_new_report("first", "123456")
    with pytest.raises(WorkspaceError, match="storage quota"):
        workspace.write_new_validation("validation-one", "12345")
    with pytest.raises(WorkspaceError, match="too large"):
        workspace.write_new_report("oversized", "123456789")
    with pytest.raises(WorkspaceError, match="already exists"):
        workspace.write_new_report("first", "x")

    assert first.read_text(encoding="utf-8") == "123456"
    assert not (workspace.root / "validation-one.md").exists()
    assert not (workspace.reports_dir / "oversized.md").exists()


def test_report_file_count_is_bounded(
    workspace: PitwallWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "MAX_ARTIFACT_FILES", 1)

    workspace.new_report_file("reserved")

    with pytest.raises(WorkspaceError, match="file limit"):
        workspace.new_validation_file("validation-two")


def test_recent_history_is_bounded_and_ignores_malformed_objects(
    workspace: PitwallWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "MAX_HISTORY_READ_BYTES", 512)
    entries = [
        {
            "timestamp": f"2026-01-01T00:00:0{index}+00:00",
            "session_id": "session",
            "role": "user",
            "content": f"entry-{index}",
            "used_tools": [],
        }
        for index in range(3)
    ]
    lines = [
        "x" * 5000,
        "[1, 2, 3]",
        '{"timestamp": "bad", "used_tools": 5}',
        *(json.dumps(entry) for entry in entries),
    ]
    workspace.memory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    recent = SessionHistory(workspace.memory_path).recent(limit=2)

    assert [entry["content"] for entry in recent] == ["entry-1", "entry-2"]


def test_history_compacts_instead_of_growing_without_bound(
    workspace: PitwallWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "MAX_HISTORY_FILE_BYTES", 250)
    monkeypatch.setattr(memory_module, "HISTORY_RETAIN_BYTES", 140)
    history = SessionHistory(workspace.memory_path)
    for index in range(12):
        history.append("session", "user", f"entry-{index}-" + "x" * 50)

    assert workspace.memory_path.stat().st_size < 600
    assert history.recent(limit=1)[0]["content"].startswith("entry-11-")


def test_telemetry_size_cap_rejects_before_copy_or_activation(
    workspace: PitwallWorkspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "MAX_TELEMETRY_BYTES", 16)
    source = tmp_path / "oversized.csv"
    source.write_bytes(b"lap,lap_time_sec\n1,120\n")

    with pytest.raises(WorkspaceError, match="too large"):
        workspace.ingest(source)

    assert list(workspace.data_dir.iterdir()) == []
    assert workspace.state()["active_telemetry"] is None


def test_telemetry_growth_during_copy_cannot_cross_workspace_quota(
    workspace: PitwallWorkspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "MAX_TELEMETRY_BYTES", 64)
    monkeypatch.setattr(workspace_module, "MAX_DATA_DIRECTORY_BYTES", 20)
    (workspace.data_dir / "existing.bin").write_bytes(b"x" * 10)
    source = tmp_path / "growing.csv"
    source.write_bytes(b"12345678")
    original_copy = workspace_module._copy_file_exclusive

    def growing_copy(source: Path, target: Path, byte_limit: int) -> str:
        digest = original_copy(source, target, byte_limit)
        with target.open("ab") as handle:
            handle.write(b"grow!")
        return digest

    monkeypatch.setattr(workspace_module, "_copy_file_exclusive", growing_copy)

    with pytest.raises(WorkspaceError, match="grew during import"):
        workspace.ingest(source)

    assert not (workspace.data_dir / "growing.csv").exists()
    assert workspace.state()["active_telemetry"] is None


def test_concurrent_ingest_serializes_quota_and_provenance_updates(
    workspace: PitwallWorkspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workspace_module, "MAX_TELEMETRY_BYTES", 16)
    monkeypatch.setattr(workspace_module, "MAX_DATA_DIRECTORY_BYTES", 24)
    (workspace.data_dir / "existing.bin").write_bytes(b"x" * 8)
    sources = []
    for name in ("one.csv", "two.csv"):
        source = tmp_path / name
        source.write_bytes(b"y" * 16)
        sources.append(source)

    original_copy = workspace_module._copy_file_exclusive
    first_copy_entered = Event()
    release_copy = Event()
    overlapping_copy = Event()
    active_copies = 0
    guard = Lock()

    def observed_copy(source: Path, target: Path, byte_limit: int) -> str:
        nonlocal active_copies
        with guard:
            active_copies += 1
            if active_copies > 1:
                overlapping_copy.set()
            first_copy_entered.set()
        try:
            assert release_copy.wait(5)
            return original_copy(source, target, byte_limit)
        finally:
            with guard:
                active_copies -= 1

    monkeypatch.setattr(workspace_module, "_copy_file_exclusive", observed_copy)
    start = Barrier(2)

    def ingest(source: Path) -> str:
        start.wait()
        try:
            return workspace.ingest(source).name
        except WorkspaceError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest, source) for source in sources]
        assert first_copy_entered.wait(5)
        assert not overlapping_copy.wait(0.25)
        release_copy.set()
        outcomes = [future.result(timeout=5) for future in futures]

    imported = [outcome for outcome in outcomes if outcome.endswith(".csv")]
    rejected = [outcome for outcome in outcomes if "quota exceeded" in outcome]
    assert len(imported) == 1
    assert len(rejected) == 1
    assert sum(item.stat().st_size for item in workspace.data_dir.iterdir()) == 24
    assert set(workspace.state()["telemetry_sources"]) == set(imported)


def test_telemetry_row_cap_prevents_memory_amplification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry_module, "MAX_TELEMETRY_ROWS", 2)
    source = "lap,lap_time_sec\n1,120\n2,121\n3,122\n"

    with pytest.raises(ValueError, match="more than 2 rows"):
        calibrate_telemetry(source)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_tool_arguments_reject_nonfinite_numbers(
    workspace: PitwallWorkspace,
    value: float,
) -> None:
    result = build_registry(workspace).execute(
        "simulate_safety_car",
        {"deploy_min": value, "duration_min": 20},
    )

    assert not result.ok
    assert "finite number" in result.error


def test_synthetic_provenance_survives_renaming_on_ingest(
    workspace: PitwallWorkspace,
) -> None:
    source = ROOT / "examples" / "spa_6h_synthetic.csv"
    imported = workspace.ingest(source, name="renamed-clean-session")

    result = build_registry(workspace).execute(
        "inspect_telemetry",
        {"file": imported.name},
    )

    assert result.ok
    assert result.data["synthetic"] is True
    assert result.data["quality"]["evidence_level"] == "C"


def test_bundled_synthetic_provenance_survives_renaming_before_ingest(
    workspace: PitwallWorkspace,
    tmp_path: Path,
) -> None:
    renamed = tmp_path / "real-session.csv"
    shutil.copyfile(ROOT / "examples" / "spa_6h_synthetic.csv", renamed)
    imported = workspace.ingest(renamed)

    result = build_registry(workspace).execute(
        "inspect_telemetry",
        {"file": imported.name},
    )

    assert result.ok
    assert result.data["synthetic"] is True
    assert result.data["quality"]["evidence_level"] == "C"

    workspace.state_path.write_text("{broken", encoding="utf-8")
    recovered = build_registry(workspace).execute(
        "inspect_telemetry",
        {"file": imported.name},
    )
    assert recovered.ok
    assert recovered.data["synthetic"] is True
    assert recovered.data["quality"]["evidence_level"] == "C"


def test_one_high_quality_real_session_cannot_claim_evidence_a() -> None:
    source = (ROOT / "examples" / "spa_6h_synthetic.csv").read_text(encoding="utf-8")

    calibration = calibrate_telemetry(
        source,
        source_name="declared-real-session.csv",
        is_synthetic=False,
    )

    assert calibration.confidence == "High"
    assert calibration.evidence_level == "B"
