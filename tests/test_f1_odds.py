"""Seeded sensitivity and the undercut sum. Neither is a rival forecast."""

from __future__ import annotations

import pytest

from engine.f1 import F1Setup, best_f1_plan
from engine.f1_odds import ODDS_HONESTY, race_time_odds, undercut
from engine.series_config import load_setup
from tests.test_f1_rules import _setup


def test_undercut_reports_the_gap_after_both_cars_stop() -> None:
    ahead = undercut(
        gap_behind_sec=2,
        laps_ahead=5,
        tyre_gain_sec_per_lap=0.5,
        our_pit_loss_sec=22,
        their_pit_loss_sec=22,
    )
    behind = undercut(
        gap_behind_sec=5,
        laps_ahead=1,
        tyre_gain_sec_per_lap=0.1,
        our_pit_loss_sec=22,
        their_pit_loss_sec=22,
    )
    level = undercut(
        gap_behind_sec=2.5,
        laps_ahead=5,
        tyre_gain_sec_per_lap=0.5,
        our_pit_loss_sec=22,
        their_pit_loss_sec=22,
    )

    assert ahead == {
        "net_sec": 0.5,
        "ahead": True,
        "tyre_gain_sec": 2.5,
        "out_lap_warmup_sec": 0.0,
        "in_lap_delta_sec": 0.0,
        "traffic_avoided_sec": 0.0,
        "explanation": "Pit 5 laps earlier and this rival is 0.500 s behind when they stop.",
        "assumption": "Tyre gain per lap is your input, not a measured rival.",
    }
    assert behind["net_sec"] == -4.9
    assert behind["ahead"] is False
    assert behind["explanation"] == (
        "Pit 1 lap earlier and this rival is still 4.900 s ahead when they stop."
    )
    assert level["net_sec"] == 0.0
    assert level["explanation"] == (
        "Pit 5 laps earlier and this rival is alongside when they stop."
    )
    with pytest.raises(ValueError, match="at least 1"):
        undercut(
            gap_behind_sec=1,
            laps_ahead=0,
            tyre_gain_sec_per_lap=0.2,
            our_pit_loss_sec=22,
            their_pit_loss_sec=22,
        )
    costly = undercut(
        gap_behind_sec=2,
        laps_ahead=5,
        tyre_gain_sec_per_lap=0.5,
        our_pit_loss_sec=22,
        their_pit_loss_sec=22,
        out_lap_warmup_sec=1.0,
        in_lap_delta_sec=0.5,
        traffic_avoided_sec=0.2,
    )
    assert costly["net_sec"] == -0.8
    assert "Out-lap warm-up" in str(costly["explanation"])
    with pytest.raises(ValueError, match="zero or higher"):
        undercut(
            gap_behind_sec=-1,
            laps_ahead=1,
            tyre_gain_sec_per_lap=0.2,
            our_pit_loss_sec=22,
            their_pit_loss_sec=22,
        )


def test_toy_odds_stay_near_the_deterministic_plan() -> None:
    setup = _setup()
    plan = best_f1_plan(setup)
    sampled = race_time_odds(
        setup, list(zip(plan.compounds_used, plan.stint_laps, strict=True))
    )

    assert plan.race_time_sec == 1016.0
    assert sampled["iterations"] == 64
    assert sampled["seed"] == 20241015
    assert sampled["feasible_runs"] == 64
    assert sampled["p10_sec"] == 1015.187
    assert sampled["p50_sec"] == 1016.045
    assert sampled["p90_sec"] == 1016.789
    assert sampled["honesty"] == ODDS_HONESTY


def test_bahrain_file_pace_odds_are_a_labelled_sample() -> None:
    setup = load_setup(2024, 1)
    plan = best_f1_plan(setup)
    sampled = race_time_odds(
        setup, list(zip(plan.compounds_used, plan.stint_laps, strict=True))
    )

    assert plan.compounds_used == ["HARD", "SOFT"]
    assert plan.stint_laps == [35, 22]
    assert sampled["p10_sec"] == 5463.525
    assert sampled["p50_sec"] == 5466.352
    assert sampled["p90_sec"] == 5468.666
    assert "not a P10–P90 forecast" in str(sampled["honesty"])


def test_odds_reject_a_bad_sample_size_and_a_missing_pit_loss() -> None:
    setup = _setup()
    with pytest.raises(ValueError, match="1 to 400"):
        race_time_odds(setup, [("HARD", 6), ("SOFT", 4)], iterations=0)
    with pytest.raises(ValueError, match="1 to 400"):
        race_time_odds(setup, [("HARD", 6), ("SOFT", 4)], iterations=401)
    bare = F1Setup(
        season=2024,
        round=1,
        event_name="Toy",
        race_laps=10,
        dry_race=True,
        time_limit_sec=2000,
        pit_lane_loss_sec=None,
        base_lap_time_sec=100.0,
        refuelling_allowed=False,
        dry_min_compounds=2,
        wet_min_compounds=1,
        max_stops=2,
        compounds=setup.compounds,
        cars=setup.cars,
        data_source="Toy assumptions.",
        evidence_level="C",
    )
    with pytest.raises(ValueError, match="pit-lane"):
        race_time_odds(bare, [("HARD", 6), ("SOFT", 4)])


def test_an_infeasible_sample_has_no_percentiles() -> None:
    sampled = race_time_odds(_setup(), [("SOFT", 9), ("HARD", 1)])

    assert sampled["feasible_runs"] == 0
    assert sampled["p10_sec"] is None
    assert sampled["p50_sec"] is None
    assert sampled["p90_sec"] is None
