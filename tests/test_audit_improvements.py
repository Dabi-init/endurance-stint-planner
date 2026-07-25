"""Regression tests for the usability and honesty fixes raised by the audit."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from pitwall.cli import app
from pitwall.guided import (
    GUIDED_FIELDS,
    PRESET_ORIGIN,
    REGULATION_NOTICE,
    USER_ORIGIN,
    GuidedValueError,
    build_race_config,
    cross_check,
    parse_field,
    preset_defaults,
    summary_rows,
)
from pitwall.redaction import REDACTION_NOTICE, anonymise_tool_payload, driver_alias_map
from pitwall.tools import (
    MANUAL_INPUT_SOURCE,
    P10_LABEL,
    P90_LABEL,
    PRE_RACE_ONLY_HEADER,
    SAFETY_CAR_DISCLAIMER,
    build_registry,
)
from pitwall.validation_report import (
    EVIDENCE_LEVEL,
    PROVENANCE_DISCLAIMERS,
    ValidationInputError,
    build_comparison,
    compare_metric,
    parse_stint_lengths,
    render_report,
    report_filename,
)
from pitwall.welcome import WELCOME_SECTIONS, welcome_payload
from pitwall.workspace import PitwallWorkspace, WorkspaceError

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path):
    space = PitwallWorkspace.from_path(tmp_path / ".pitwall")
    space.initialise()
    return space


def cli(tmp_path, *args):
    return runner.invoke(app, ["--home", str(tmp_path / ".pitwall"), *args])


# --------------------------------------------------------------------------
# B1 / B5 / B6: pit sheet completeness and honest percentile labels
# --------------------------------------------------------------------------


def test_pit_sheet_contains_every_decision_field(workspace):
    result = build_registry(workspace).execute(
        "export_pit_sheet", {"name": "audit-sheet"}
    )
    assert result.ok, result.error
    text = (workspace.reports_dir / "audit-sheet.md").read_text(encoding="utf-8")
    for expected in (
        PRE_RACE_ONLY_HEADER,
        P10_LABEL,
        P90_LABEL,
        "PESSIMISTIC",
        "OPTIMISTIC",
        "Evidence Level",
        "Uncertainty source",
        "Tyre age at stint end (laps)",
        "Pit stop after (s)",
        "## Assumptions",
        "## Trigger cards",
    ):
        assert expected in text, expected


def test_pit_sheet_states_evidence_level_in_plain_english(workspace):
    build_registry(workspace).execute("export_pit_sheet", {"name": "meaning"})
    text = (workspace.reports_dir / "meaning.md").read_text(encoding="utf-8")
    assert "Assumed, preset, or synthetic values" in text
    assert "confidence" in text.lower()


def test_percentile_labels_are_used_in_plan_and_comparison(workspace):
    registry = build_registry(workspace)
    plan = registry.execute("plan_race", {})
    comparison = registry.execute("compare_race_strategies", {})
    assert plan.data["simulation"]["laps_p10_label"] == P10_LABEL
    assert plan.data["simulation"]["laps_p90_label"] == P90_LABEL
    assert comparison.data["percentile_labels"] == {
        "P10 laps": P10_LABEL,
        "P90 laps": P90_LABEL,
    }


# --------------------------------------------------------------------------
# B2: export defaults to the recommended strategy
# --------------------------------------------------------------------------


def test_export_defaults_to_the_recommended_strategy(workspace):
    registry = build_registry(workspace)
    recommended = registry.execute("compare_race_strategies", {}).data["recommendation"]
    default_export = registry.execute("export_pit_sheet", {"name": "default"})
    assert default_export.data["strategy"] == recommended
    assert default_export.data["recommended"] is True


def test_export_strategy_option_overrides_the_recommendation(workspace):
    registry = build_registry(workspace)
    recommended = registry.execute("compare_race_strategies", {}).data["recommendation"]
    other = next(
        name
        for name in ("Conservative", "Balanced", "Fuel Save")
        if name != recommended
    )
    override = registry.execute(
        "export_pit_sheet", {"name": "override", "strategy": other}
    )
    assert override.data["strategy"] == other
    assert override.data["recommended"] is False


def test_export_help_documents_the_default(tmp_path):
    result = cli(tmp_path, "export", "--help")
    assert result.exit_code == 0
    assert "recommended" in result.stdout


# --------------------------------------------------------------------------
# B3 / B4: onboarding
# --------------------------------------------------------------------------


def test_welcome_covers_every_beginner_topic(tmp_path):
    result = cli(tmp_path, "--json", "welcome")
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    headings = " ".join(section["heading"] for section in payload["sections"]).lower()
    for topic in (
        "stint",
        "fuel reserve",
        "tyre life",
        "p10",
        "evidence level",
        "parallel",
        "safety car",
        "telemetry",
        "cannot know",
    ):
        assert topic in headings, topic
    assert payload["guided_offer"]
    assert welcome_payload()["sections"][0]["heading"] == WELCOME_SECTIONS[0][0]


def test_readme_glossary_defines_the_core_terms():
    from pathlib import Path

    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "## Glossary" in text
    glossary = text.split("## Glossary", 1)[1]
    for term in (
        "**Stint**",
        "**Fuel reserve**",
        "**Tyre life**",
        "**P10 / P90**",
        "**Evidence Level A / B / C**",
        "**Parallel vs sequential pit service**",
        "**Safety Car scenario**",
        "**Trigger card**",
        "**Deterministic engine**",
        "**Telemetry**",
    ):
        assert term in glossary, term


# --------------------------------------------------------------------------
# B6: the Safety Car disclaimer travels with every surface
# --------------------------------------------------------------------------


def test_safety_car_disclaimer_in_tool_payload_and_notes(workspace):
    result = build_registry(workspace).execute(
        "simulate_safety_car", {"deploy_min": 120, "duration_min": 20}
    )
    assert result.ok, result.error
    assert result.data["disclaimer"] == SAFETY_CAR_DISCLAIMER
    assert result.data["notes"][0] == SAFETY_CAR_DISCLAIMER


def test_safety_car_disclaimer_in_cli_and_json(tmp_path):
    text_run = cli(tmp_path, "scenario", "120", "20")
    json_run = cli(tmp_path, "--json", "scenario", "120", "20")
    assert text_run.exit_code == 0 and json_run.exit_code == 0
    assert "PRE-RACE WHAT-IF ONLY" in text_run.stdout
    payload = json.loads(json_run.stdout)
    assert payload["disclaimer"] == SAFETY_CAR_DISCLAIMER


def test_pit_sheet_and_plan_carry_the_pre_race_header(workspace):
    plan = build_registry(workspace).execute("plan_race", {})
    assert plan.data["pre_race_only"] == PRE_RACE_ONLY_HEADER


# --------------------------------------------------------------------------
# B7: driver labels are scrubbed from model-visible payloads
# --------------------------------------------------------------------------


def test_driver_names_are_aliased_for_the_model(workspace):
    payload = build_registry(workspace).execute("plan_race", {}).to_dict()
    real_names = [stint["Driver"] for stint in payload["plan"]["stints"]]
    redacted = anonymise_tool_payload(payload)
    text = json.dumps(redacted)
    assert "Driver_1" in text
    for name in set(real_names):
        assert name not in text
    assert REDACTION_NOTICE in json.dumps(redacted)


def test_driver_alias_map_is_stable_and_ordered():
    aliases = driver_alias_map(
        {"stints": [{"Driver": "Sam"}, {"Driver": "Alex"}, {"Driver": "Sam"}]}
    )
    assert aliases == {"Sam": "Driver_1", "Alex": "Driver_2"}
    assert driver_alias_map({"laps": 12}) == {}
    assert anonymise_tool_payload({"laps": 12}) == {"laps": 12}


def test_user_facing_output_keeps_real_driver_names(workspace):
    payload = build_registry(workspace).execute("plan_race", {}).to_dict()
    names = {stint["Driver"] for stint in payload["plan"]["stints"]}
    assert not any(name.startswith("Driver_") for name in names)


# --------------------------------------------------------------------------
# B8: non-overwrite protection lives in the workspace
# --------------------------------------------------------------------------


def test_workspace_refuses_to_overwrite_a_report(workspace):
    first = workspace.new_report_file("sheet")
    first.write_text("existing", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        workspace.new_report_file("sheet")


def test_workspace_refuses_to_overwrite_a_validation_report(workspace):
    target = workspace.new_validation_file("validation_20260101-000000")
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        workspace.new_validation_file("validation_20260101-000000")


def test_export_tool_surfaces_the_workspace_error(workspace):
    registry = build_registry(workspace)
    assert registry.execute("export_pit_sheet", {"name": "twice"}).ok
    second = registry.execute("export_pit_sheet", {"name": "twice"})
    assert not second.ok
    assert "already exists" in second.error


# --------------------------------------------------------------------------
# B9: manual assumptions versus telemetry-calibrated inputs
# --------------------------------------------------------------------------


def test_manual_inputs_are_reported_as_manual_assumptions(workspace):
    registry = build_registry(workspace)
    for tool in ("plan_race", "compare_race_strategies"):
        payload = registry.execute(tool, {}).data
        assert payload["input_source"] == MANUAL_INPUT_SOURCE
        assert payload["evidence"]["input_source"] == MANUAL_INPUT_SOURCE


def test_cli_compare_shows_the_input_source(tmp_path):
    result = cli(tmp_path, "compare")
    assert result.exit_code == 0
    assert "Input source" in result.stdout


# --------------------------------------------------------------------------
# C.1: trigger cards reach the plan, the comparison, and the pit sheet
# --------------------------------------------------------------------------


def test_trigger_cards_are_exposed_by_the_tools(workspace):
    registry = build_registry(workspace)
    for tool in ("plan_race", "compare_race_strategies"):
        cards = registry.execute(tool, {}).data["trigger_cards"]
        assert len(cards) == 6
        assert all(card["status"] in {"HOLD", "RECONSIDER"} for card in cards)


def test_trigger_cards_reach_the_pit_sheet(workspace):
    build_registry(workspace).execute("export_pit_sheet", {"name": "cards"})
    text = (workspace.reports_dir / "cards.md").read_text(encoding="utf-8")
    assert "## Trigger cards" in text
    assert "RECONSIDER" in text or "HOLD" in text


# --------------------------------------------------------------------------
# C.2: guided setup validation and provenance labels
# --------------------------------------------------------------------------


def test_guided_fields_declare_units_and_safe_ranges():
    for field in GUIDED_FIELDS:
        assert field.unit
        assert field.minimum < field.maximum
        assert field.help_text


def test_guided_empty_answer_is_labelled_as_the_preset_default():
    defaults = preset_defaults()
    value, origin = parse_field(
        "base_lap_time_sec", "   ", defaults["base_lap_time_sec"]
    )
    assert value == defaults["base_lap_time_sec"]
    assert origin == PRESET_ORIGIN


def test_guided_answer_is_labelled_as_user_input():
    value, origin = parse_field("base_lap_time_sec", "118.5", 120.0)
    assert value == 118.5
    assert origin == USER_ORIGIN


@pytest.mark.parametrize(
    "key,raw",
    [
        ("race_duration_hours", "0"),
        ("race_duration_hours", "not-a-number"),
        ("base_lap_time_sec", "-5"),
        ("fuel_tank_liters", "1e9"),
        ("tyre_life_laps", "12.5"),
        ("driver_count", "0"),
    ],
)
def test_guided_rejects_impossible_values(key, raw):
    with pytest.raises(GuidedValueError):
        parse_field(key, raw, 1)


def test_guided_cross_check_catches_impossible_combinations():
    problems = cross_check(
        {
            "race_duration_hours": 1.0,
            "base_lap_time_sec": 120.0,
            "fuel_consumption_per_lap": 90.0,
            "fuel_tank_liters": 50.0,
            "tyre_life_laps": 20,
            "driver_count": 3,
            "min_driver_time_min": 120.0,
        }
    )
    assert any("larger than the usable tank" in problem for problem in problems)
    assert any("exceeds the" in problem for problem in problems)


def test_guided_build_race_config_uses_answers_and_keeps_regulations_separate():
    values = {
        "race_duration_hours": 4.0,
        "base_lap_time_sec": 100.0,
        "fuel_consumption_per_lap": 2.5,
        "fuel_tank_liters": 80.0,
        "tyre_life_laps": 30,
        "driver_count": 2,
        "min_driver_time_min": 45.0,
    }
    config = build_race_config(values, race_name="Guided test")
    assert config.race_duration_hours == 4.0
    assert config.tyre_life_laps == 30
    assert len(config.drivers) == 2
    assert config.regulations.bronze_min_drive_min == 45.0
    assert "not official regulations" in REGULATION_NOTICE
    assert config.data_source.startswith("Manual assumptions")


def test_guided_build_race_config_refuses_an_impossible_combination():
    with pytest.raises(GuidedValueError):
        build_race_config(
            {
                "race_duration_hours": 1.0,
                "base_lap_time_sec": 100.0,
                "fuel_consumption_per_lap": 100.0,
                "fuel_tank_liters": 50.0,
                "tyre_life_laps": 20,
                "driver_count": 1,
                "min_driver_time_min": 0.0,
            }
        )


def test_guided_summary_rows_show_where_each_value_came_from():
    defaults = preset_defaults()
    origins = {field.key: PRESET_ORIGIN for field in GUIDED_FIELDS}
    origins["base_lap_time_sec"] = USER_ORIGIN
    rows = summary_rows(defaults, origins)
    assert len(rows) == len(GUIDED_FIELDS)
    assert [row[3] for row in rows].count(USER_ORIGIN) == 1
    assert GUIDED_FIELDS[0].unknown_hint(defaults[GUIDED_FIELDS[0].key])


def test_guided_cli_writes_a_race_after_confirmation(tmp_path):
    answers = "4\n100\n2.5\n80\n30\n2\n45\ny\n"
    result = cli(tmp_path, "init", "--guided", "--replace")
    assert result.exit_code in {0, 1}  # no stdin: exercised below with input
    result = runner.invoke(
        app,
        ["--home", str(tmp_path / ".pitwall"), "init", "--guided", "--replace"],
        input=answers,
    )
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".pitwall" / "race.json").exists()
    assert REGULATION_NOTICE.split(".")[0] in result.stdout.replace("\n", " ")


def test_guided_cli_writes_nothing_when_declined(tmp_path):
    answers = "4\n100\n2.5\n80\n30\n2\n45\nn\n"
    result = runner.invoke(
        app,
        ["--home", str(tmp_path / ".pitwall"), "init", "--guided"],
        input=answers,
    )
    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / ".pitwall" / "race.json").exists()


def test_guided_cli_reprompts_after_an_invalid_value(tmp_path):
    answers = "0\n4\n100\n2.5\n80\n30\n2\n45\ny\n"
    result = runner.invoke(
        app,
        ["--home", str(tmp_path / ".pitwall"), "init", "--guided", "--replace"],
        input=answers,
    )
    assert result.exit_code == 0, result.stdout
    assert "Please try again" in result.stdout


# --------------------------------------------------------------------------
# C.3: plan versus reported result
# --------------------------------------------------------------------------


def test_validation_arithmetic_is_relative_to_the_plan():
    row = compare_metric("Laps completed", "laps", 200.0, 210.0)
    assert row.difference == 10.0
    assert row.deviation_pct == 5.0
    zero = compare_metric("Laps completed", "laps", 0.0, 5.0)
    assert zero.deviation_pct is None


def test_validation_comparison_skips_metrics_without_actuals():
    rows = build_comparison(
        {"laps": 200.0, "stops": 6.0, "fuel_burn_per_lap": 2.9},
        {"laps": 195.0, "stops": None, "fuel_burn_per_lap": None},
    )
    assert [row.metric for row in rows] == ["Laps completed"]
    assert rows[0].difference == -5.0


def test_validation_stint_lengths_are_parsed_and_validated():
    assert parse_stint_lengths("18, 19,17") == [18, 19, 17]
    assert parse_stint_lengths(None) == []
    with pytest.raises(ValidationInputError):
        parse_stint_lengths("18,x")
    with pytest.raises(ValidationInputError):
        parse_stint_lengths("18,-3")


def test_validation_report_carries_provenance_disclaimers():
    planned = {"laps": 200.0, "stops": 6.0, "stint_lengths": [20, 20]}
    actual = {"laps": 195.0, "stops": 7.0, "stint_lengths": [18, 19, 17]}
    rows = build_comparison(planned, actual)
    markdown = render_report(
        "Test race",
        "Balanced",
        planned,
        actual,
        rows,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    for disclaimer in PROVENANCE_DISCLAIMERS:
        assert disclaimer in markdown
    assert f"Evidence Level: **{EVIDENCE_LEVEL}**" in markdown
    assert "Stint-by-stint laps" in markdown
    assert "-2.50%" in markdown


def test_validation_report_filename_is_timestamped():
    name = report_filename(datetime(2026, 7, 26, 10, 30, 5, tzinfo=UTC))
    assert name == "validation_20260726-103005"


def test_validate_command_writes_a_report(tmp_path):
    result = cli(
        tmp_path,
        "--json",
        "validate",
        "--actual-laps",
        "205",
        "--actual-stops",
        "7",
        "--actual-fuel-burn",
        "3.05",
        "--actual-stint-lengths",
        "18,19,17",
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["evidence_level"] == "C"
    assert payload["disclaimers"] == PROVENANCE_DISCLAIMERS
    report = tmp_path / ".pitwall" / (payload["created"].rsplit("/", 1)[-1])
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "not independently validated" in text


def test_validate_command_requires_at_least_one_actual(tmp_path):
    result = cli(tmp_path, "validate")
    assert result.exit_code != 0


def test_validate_command_rejects_malformed_stint_lengths(tmp_path):
    result = cli(tmp_path, "validate", "--actual-stint-lengths", "18,oops")
    assert result.exit_code != 0
