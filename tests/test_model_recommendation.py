"""Regression coverage for the read-only Ollama recommendation flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import pitwall.cli as cli_module
from pitwall.cli import app
from pitwall.model_advisor import (
    CORE_ONLY,
    FIRST_TRY,
    MODEL_OPTIONS,
    SMALLER_CANDIDATE,
)

RUNNER = CliRunner()
ROOT = Path(__file__).resolve().parent.parent


def test_model_catalog_leads_with_the_verified_operational_path() -> None:
    assert MODEL_OPTIONS == (CORE_ONLY, FIRST_TRY, SMALLER_CANDIDATE)
    assert CORE_ONLY.to_dict()["status"] == "verified-operational-path"
    assert CORE_ONLY.to_dict()["pull_command"] is None
    assert FIRST_TRY.to_dict()["model"] == "qwen3:8b"
    assert SMALLER_CANDIDATE.to_dict()["model"] == "qwen3:4b"
    assert all(
        option.to_dict()["status"] == "unverified-candidate"
        for option in (FIRST_TRY, SMALLER_CANDIDATE)
    )


def test_json_recommendation_is_read_only_and_does_not_probe_ollama(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "must-not-be-created"
    monkeypatch.setattr(
        cli_module,
        "list_local_models",
        lambda _settings: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )

    result = RUNNER.invoke(
        app,
        ["--home", str(home), "--json", "model", "recommend"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "provisional"
    assert payload["provider"] == "ollama-only"
    assert payload["operational_default"]["model"] is None
    assert payload["optional_first_try"]["model"] == "qwen3:8b"
    assert [option["model"] for option in payload["choices"]] == [
        None,
        "qwen3:8b",
        "qwen3:4b",
    ]
    assert payload["pitwall_conformance_tested"] is False
    assert payload["changes_made"] is False
    assert payload["downloads_started"] is False
    assert not home.exists()


def test_text_recommendation_shows_all_choices_and_no_side_effects(
    tmp_path: Path,
) -> None:
    home = tmp_path / "must-not-be-created"
    result = RUNNER.invoke(app, ["--home", str(home), "model", "recommend"])

    assert result.exit_code == 0, result.stdout
    for expected in (
        "qwen3:8b",
        "qwen3:4b",
        "5.2 GB",
        "2.5 GB",
        "Nothing was downloaded",
        "Core-only remains the verified operational path",
        "pitwall model use qwen3:8b",
        "does not test real-model tool-calling",
        "quality or hardware fit",
    ):
        assert expected in result.stdout
    assert "best" not in result.stdout.lower()
    assert not home.exists()


def test_recommendation_preserves_an_existing_config_byte_for_byte(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".pitwall"
    home.mkdir()
    config = home / "config.toml"
    original = b'# custom bytes stay exact\nprovider = "none"\n'
    config.write_bytes(original)

    result = RUNNER.invoke(app, ["--home", str(home), "model", "recommend"])

    assert result.exit_code == 0, result.stdout
    assert config.read_bytes() == original
    assert list(home.iterdir()) == [config]


@pytest.mark.parametrize(
    "relative_path",
    ["README.md", "docs/index.html", "docs/LAUNCH.md", "docs/PROJECT_HANDOFF.md"],
)
def test_model_guidance_is_shipped_but_explicitly_unverified(
    relative_path: str,
) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8").lower()

    for expected in (
        "pitwall model recommend",
        "qwen3:8b",
        "qwen3:4b",
        "5.2 gb",
        "2.5 gb",
        "core-only",
        "unverified",
    ):
        assert expected in text
    assert "best current" not in text
    assert "model recommend` is planned" not in text
    assert "scripts\\pitwall.exe" not in text
