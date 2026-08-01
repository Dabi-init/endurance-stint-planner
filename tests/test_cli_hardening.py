"""Regression tests for install and command-line reliability."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

import pitwall.cli as cli_module
from pitwall.cli import _trigger_condition, app
from pitwall.config import Settings
from pitwall.providers import ProviderError

RUNNER = CliRunner()
ROOT = Path(__file__).resolve().parent.parent


def _run(home: Path, *arguments: str):
    return RUNNER.invoke(app, ["--home", str(home), *arguments])


def test_development_extra_is_real_and_matches_the_dev_requirements() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["optional-dependencies"]["dev"]
    assert (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").strip() == (
        "-e .[dev]"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ("plan", "--strategy", "Bogus"),
        ("compare", "--preset", "not-a-preset"),
        ("scenario", "--", "-1", "20"),
    ],
)
def test_json_tool_failures_have_nonzero_exit_status(
    tmp_path: Path, arguments: tuple[str, ...]
) -> None:
    result = _run(tmp_path / ".pitwall", "--json", *arguments)
    assert result.exit_code == 1, result.stdout
    assert json.loads(result.stdout)["ok"] is False


def test_duplicate_export_is_a_failure_in_text_and_json(tmp_path: Path) -> None:
    home = tmp_path / ".pitwall"
    first = _run(home, "export", "--name", "same")
    duplicate = _run(home, "export", "--name", "same")
    duplicate_json = _run(home, "--json", "export", "--name", "same")

    assert first.exit_code == 0, first.stdout
    assert duplicate.exit_code == 1
    assert "Not created" in duplicate.stdout
    assert duplicate_json.exit_code == 1
    assert json.loads(duplicate_json.stdout)["ok"] is False


@pytest.mark.parametrize(
    "arguments",
    [
        ("race", "init", "--preset", "bogus"),
        ("race", "init"),
    ],
)
def test_json_race_init_runtime_failures_are_json(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    home = tmp_path / ".pitwall"
    if arguments == ("race", "init"):
        assert _run(home, *arguments).exit_code == 0

    result = _run(home, "--json", *arguments)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_malformed_config_is_controlled_and_doctor_fails(tmp_path: Path) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "init").exit_code == 0
    (home / "config.toml").write_text("provider = [", encoding="utf-8")

    result = _run(home, "doctor")

    assert result.exit_code == 1
    assert "configuration" in result.stdout
    assert "Traceback" not in result.stdout


def test_doctor_fails_when_selected_ollama_model_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "model", "use", "local-model", "--force").exit_code == 0
    monkeypatch.setattr(
        cli_module,
        "list_local_models",
        lambda _settings: (_ for _ in ()).throw(ProviderError("not running")),
    )

    result = _run(home, "--json", "doctor")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    ollama = next(item for item in payload["checks"] if item["check"] == "Ollama")
    assert ollama["status"] == "fail"
    assert "selected model unavailable" in ollama["detail"]


def test_doctor_does_not_probe_ollama_when_model_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "init").exit_code == 0
    monkeypatch.setattr(
        cli_module,
        "list_local_models",
        lambda _settings: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )

    result = _run(home, "--json", "doctor")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    ollama = next(item for item in payload["checks"] if item["check"] == "Ollama")
    assert ollama["status"] == "optional"
    assert "no local service contacted" in ollama["detail"]


def test_core_only_doctor_skips_configured_ollama(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "model", "use", "local-model", "--force").exit_code == 0
    monkeypatch.setattr(
        cli_module,
        "list_local_models",
        lambda _settings: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )

    result = _run(home, "--json", "doctor", "--core-only")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    ollama = next(item for item in payload["checks"] if item["check"] == "Ollama")
    assert ollama["status"] == "optional"
    assert "core-only" in ollama["detail"]


def test_non_boolean_history_setting_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('remember_sessions = "false"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="must be true or false"):
        Settings.load(path)


def test_failed_telemetry_inspection_rolls_back_the_import(tmp_path: Path) -> None:
    home = tmp_path / ".pitwall"
    source = tmp_path / "invalid.csv"
    source.write_bytes(b"lap,lap_time_sec\n1,\xff\n")

    result = _run(home, "--json", "ingest", str(source))

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["imported"] is None
    assert list((home / "data").iterdir()) == []
    assert json.loads((home / "state.json").read_text())["active_telemetry"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        ("race", "set", "--duration", "nan"),
        ("race", "set", "--drivers", "A:Pro:nan"),
    ],
)
def test_nonfinite_race_edits_fail_without_traceback(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "race", "init").exit_code == 0

    result = _run(home, "--json", *arguments)

    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ("--actual-fuel-burn", "nan"),
        ("--actual-stint-lengths", "nan"),
    ],
)
def test_nonfinite_validation_inputs_do_not_write_reports(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    home = tmp_path / ".pitwall"
    assert _run(home, "race", "init").exit_code == 0

    result = _run(home, "--json", "validate", *arguments)

    assert result.exit_code != 0
    assert "NaN" not in result.stdout
    assert list(home.glob("validation-*.md")) == []


def test_trigger_thresholds_are_human_readable() -> None:
    base = {"unit": "litres/lap", "threshold_low": None, "threshold_high": 2.9}
    assert _trigger_condition(base) == "> 2.9 litres/lap"
    base.update(threshold_low=2.7, threshold_high=None)
    assert _trigger_condition(base) == "< 2.7 litres/lap"
    base.update(threshold_high=2.9)
    assert _trigger_condition(base) == "outside 2.7–2.9 litres/lap"


def test_interactive_accepts_the_launcher_welcome_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["pitwall welcome", "/exit"])
    welcome_calls: list[bool] = []

    class GuardAgent:
        def __init__(self, _workspace: object) -> None:
            pass

        def ask(self, _question: str, *, session_id: str):
            raise AssertionError(
                f"welcome command leaked into chat session {session_id}"
            )

    monkeypatch.setattr(
        cli_module.Prompt, "ask", lambda *_args, **_kwargs: next(answers)
    )
    monkeypatch.setattr(cli_module, "PitwallAgent", GuardAgent)
    monkeypatch.setattr(
        cli_module, "_print_welcome_content", lambda: welcome_calls.append(True)
    )

    cli_module._interactive(cli_module.State(tmp_path / ".pitwall", json_output=False))

    assert welcome_calls == [True]
