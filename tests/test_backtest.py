"""Exact recorded-versus-predicted numbers for the bundled Bahrain back-test."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backtest.__main__ import main
from backtest.harness import HONESTY, render, run_fixture
from engine.series_config import IMAGE_POLICY

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "backtest" / "fixtures" / "2024_r01_bahrain_verstappen.json"
NOTE = (
    "Predicted 1 stop (Hard 35, Soft 22), stop lap 35. "
    "Recorded 2 stops (Soft 17, Hard 20, Soft 20), stop laps 17 and 37."
)


def test_bahrain_report_matches_the_recorded_fixture() -> None:
    report = run_fixture("2024-r01-bahrain-verstappen")

    assert report.event_name == "Bahrain Grand Prix"
    assert report.season == 2024
    assert report.round == 1
    assert report.driver_number == 1
    assert report.driver_code == "VER"
    assert report.team_colour == "3671c6"
    assert report.headshot_url is not None
    assert report.headshot_url.startswith("https://")
    assert report.livery_image_url is None
    assert report.actual_compounds == ("SOFT", "HARD", "SOFT")
    assert report.actual_stint_laps == (17, 20, 20)
    assert report.actual_stop_laps == (17, 37)
    assert report.actual_pit_durations_sec == (25.064, 24.209)
    assert report.actual_race_time_sec == 5504.742
    assert report.predicted_compounds == ("HARD", "SOFT")
    assert report.predicted_stint_laps == (35, 22)
    assert report.predicted_stop_laps == (35,)
    assert report.predicted_race_time_sec == 5496.363
    assert report.replay_race_time_sec == 5504.713
    assert report.race_time_delta_sec == -8.379
    assert report.replay_time_delta_sec == -0.029
    assert report.stop_count_delta == -1
    assert report.same_stop_count is False
    assert report.stint_length_deltas is None
    assert report.pace_anchor_sec == 95.529
    assert report.evidence_level == "C"
    assert report.image_policy == IMAGE_POLICY
    assert report.notes[0] == HONESTY
    assert NOTE in report.notes
    assert any(
        "tyre age at the start of stint 1 was 3" in note for note in report.notes
    )
    assert any("CC BY-NC-SA 4.0" in note for note in report.notes)


def test_render_prints_both_times_and_the_honesty_line() -> None:
    text = render(run_fixture())

    assert text.splitlines()[0] == "2024 Bahrain Grand Prix — car 1 VER"
    assert "Recorded: Soft 17, Hard 20, Soft 20" in text
    assert "Recorded stops: stop laps 17 and 37" in text
    assert "Predicted: Hard 35, Soft 22" in text
    assert "Predicted stops: stop lap 35" in text
    assert "Recorded race time: 1:31:44.742 (5504.742 s)" in text
    assert "Predicted race time: 1:31:36.363 (5496.363 s)" in text
    assert "Predicted minus recorded: -8.379 s" in text
    assert "Recorded stints scored by the time model: 1:31:44.713 (5504.713 s)" in text
    assert "Evidence C" in text
    assert HONESTY in text
    assert NOTE in text


def test_cli_prints_the_report_without_touching_the_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("back-test must not call HTTP")

    monkeypatch.setattr(httpx.Client, "get", boom)
    monkeypatch.setattr(httpx.Client, "request", boom)

    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Predicted minus recorded: -8.379 s" in captured.out
    assert NOTE in captured.out
    assert captured.err == ""


def test_unknown_fixture_and_bad_file_fail_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ValueError, match="Unknown back-test fixture"):
        run_fixture("../pyproject.toml")

    missing = tmp_path / "missing.json"
    assert main(["--fixture", str(missing)]) == 1
    assert "Unknown back-test fixture" in capsys.readouterr().err

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert main(["--fixture", str(broken)]) == 1
    broken_err = capsys.readouterr().err
    assert "not valid JSON" in broken_err
    assert "KeyError" not in broken_err

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert main(["--fixture", str(empty)]) == 1
    empty_err = capsys.readouterr().err
    assert "missing" in empty_err
    assert "stints" in empty_err
    assert "KeyError" not in empty_err

    partial = tmp_path / "partial.json"
    partial.write_text(
        json.dumps(
            {
                "season": 2024,
                "round": 1,
                "event_name": "Toy",
                "driver_number": 1,
                "driver_code": "VER",
                "race_laps": 10,
                "stints": [{"laps": 10, "lap_start": 1, "lap_end": 10}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["--fixture", str(partial)]) == 1
    partial_err = capsys.readouterr().err
    assert "missing compound" in partial_err
    assert "KeyError" not in partial_err

    typed = tmp_path / "typed.json"
    typed.write_text(
        json.dumps(
            {
                "season": "two-thousand",
                "round": 1,
                "event_name": "Toy",
                "driver_number": 1,
                "driver_code": "VER",
                "race_laps": 10,
                "stints": [],
            }
        ),
        encoding="utf-8",
    )
    assert main(["--fixture", str(typed)]) == 1
    typed_err = capsys.readouterr().err
    assert "could not be read" in typed_err
    assert "KeyError" not in typed_err


def test_fixture_is_small_and_holds_no_image_bytes() -> None:
    raw = FIXTURE.read_bytes()

    assert len(raw) < 20_000
    assert b"\x89PNG" not in raw
    assert b"data:image" not in raw
    assert ".cache/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
