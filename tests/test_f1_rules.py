"""Exact-number tests for the F1 rule pack."""

from __future__ import annotations

from engine.f1 import (
    CarSpec,
    CompoundSpec,
    DriverSpec,
    F1Setup,
    SafetyCarRequest,
    ScenarioRequest,
    StintRequest,
    UpgradeSpec,
    best_f1_plan,
    best_lap_split,
    compare_f1,
    lap_time_ms,
    legal_one_stop_window,
    replan_f1_safety_car,
    score_stints,
)


def _car(**overrides: object) -> CarSpec:
    payload = {
        "car_id": "car",
        "fuel_capacity_kg": 20.0,
        "fuel_consumption_kg_per_lap": 1.5,
        "starting_fuel_kg": 20.0,
    }
    payload.update(overrides)
    return CarSpec(**payload)  # type: ignore[arg-type]


def _setup(**overrides: object) -> F1Setup:
    setup = F1Setup(
        season=2024,
        round=1,
        event_name="Toy",
        race_laps=10,
        dry_race=True,
        time_limit_sec=2000,
        pit_lane_loss_sec=20.0,
        base_lap_time_sec=100.0,
        refuelling_allowed=False,
        dry_min_compounds=2,
        wet_min_compounds=1,
        max_stops=2,
        compounds=[
            CompoundSpec("SOFT", "Soft", True, "FF1E00", 4, -1.0, 0.0),
            CompoundSpec("HARD", "Hard", True, "F0F0F0", 10, 0.0, 0.0),
        ],
        cars=[_car()],
        data_source="Toy assumptions.",
        evidence_level="C",
    )
    for key, value in overrides.items():
        setattr(setup, key, value)
    return setup


def test_best_lap_split_prefers_the_faster_tyre_and_breaks_ties_lexicographically() -> (
    None
):
    soft_then_hard = best_lap_split(
        10,
        [4, 10],
        [lambda laps: laps * 99_000, lambda laps: laps * 100_000],
    )
    hard_then_soft = best_lap_split(
        10,
        [10, 4],
        [lambda laps: laps * 100_000, lambda laps: laps * 99_000],
    )
    tied = best_lap_split(
        10,
        [10, 10],
        [lambda laps: laps * 100_000, lambda laps: laps * 100_000],
    )

    assert soft_then_hard == [4, 6]
    assert hard_then_soft == [6, 4]
    assert tied == [1, 9]
    assert best_lap_split(1, [4, 10], [lambda laps: 0, lambda laps: 0]) is None
    assert best_lap_split(10, [4, 4], [lambda laps: 0, lambda laps: 0]) is None


def test_lap_time_ms_rounds_each_lap() -> None:
    assert lap_time_ms(100.0, 0.0, 0.0, 0) == 100_000
    assert lap_time_ms(90.0, 0.0, 0.05, 0) == 90_000
    assert lap_time_ms(90.0, 0.0, 0.05, 1) == 90_050
    assert lap_time_ms(90.0, 0.0, 0.05, 2) == 90_100


def test_suggested_plan_is_six_hard_laps_then_four_soft() -> None:
    plan = best_f1_plan(_setup())

    assert plan.feasible is True
    assert plan.compounds_used == ["HARD", "SOFT"]
    assert plan.stint_laps == [6, 4]
    assert plan.stop_laps == [6]
    assert plan.pit_stops == 1
    assert plan.race_time_sec == 1016.0
    assert plan.fuel_used_kg == 15.0
    assert plan.candidates_checked == 8
    assert plan.summary == (
        "One pit stop. 6 laps on the Hard tyre and 4 laps on the Soft tyre. "
        "Estimated race time 16:56.000. The car does not refuel during the race."
    )
    assert plan.why == (
        "A dry race in this rule file needs at least 2 different tyre types. "
        "This plan uses Hard and Soft. "
        "Every stint stays within the tyre life in the file."
    )
    assert plan.uncertainty.startswith("Not estimated.")
    fuel = next(rule for rule in plan.rules if rule.rule_id == "fuel_range")
    assert fuel.passed is True
    assert fuel.detail == (
        "Fuel used 15.000 kg of 20.000 kg on board. No fuel is added at the stops."
    )


def test_driver_pace_and_team_upgrades_stack_on_every_lap() -> None:
    setup = _setup(
        drivers=[
            DriverSpec("VER", 1, "Max Verstappen", pace_delta_sec=-1.0),
            DriverSpec("HAM", 44, "Lewis Hamilton", pace_delta_sec=0.0),
        ],
        focus_driver="VER",
        cars=[
            _car(
                upgrades=(
                    UpgradeSpec("floor", -0.5),
                    UpgradeSpec("wing", -0.5),
                )
            )
        ],
    )

    plan = best_f1_plan(setup)

    assert plan.feasible is True
    assert plan.race_time_sec == 996.0
    assert plan.pace_base_sec == 98.0
    assert any("floor" in note and "wing" in note for note in plan.assumptions)


def test_one_driver_is_used_when_focus_is_empty() -> None:
    setup = _setup(drivers=[DriverSpec("VER", 1, pace_delta_sec=-1.0)])

    plan = best_f1_plan(setup)

    assert plan.feasible is True
    assert plan.race_time_sec == 1006.0
    assert any("only driver" in note and "VER" in note for note in plan.assumptions)


def test_two_drivers_without_a_focus_are_refused() -> None:
    setup = _setup(
        drivers=[
            DriverSpec("VER", 1),
            DriverSpec("HAM", 44),
        ]
    )

    plan = best_f1_plan(setup)

    assert plan.feasible is False
    assert plan.infeasibilities[0].code == "missing_focus"
    assert plan.summary.startswith("This setup cannot make a legal plan.")


def test_hard_only_user_plan_fails_the_dry_compound_rule() -> None:
    plan = score_stints(_setup(), [StintRequest("HARD", 10)], name="One tyre")

    assert plan.feasible is False
    assert plan.race_time_sec == 1000.0
    assert any(issue.code == "compound_rule" for issue in plan.infeasibilities)
    assert plan.rules[2].rule_id == "compound_count"
    assert plan.rules[2].passed is False


def test_stint_laps_must_add_up_and_tyres_must_be_known() -> None:
    short = score_stints(_setup(), [StintRequest("HARD", 4), StintRequest("SOFT", 5)])
    unknown = score_stints(_setup(), [StintRequest("ULTRA", 10)])

    assert short.feasible is False
    assert short.race_time_sec is None
    assert short.infeasibilities[0].code == "lap_sum"
    assert short.infeasibilities[0].message == (
        "The stints add up to 9 laps, not the 10-lap race."
    )
    assert unknown.infeasibilities[0].code == "unknown_compound"


def test_soft_stint_past_its_life_is_not_legal() -> None:
    plan = score_stints(
        _setup(),
        [StintRequest("SOFT", 6), StintRequest("HARD", 4)],
    )

    assert plan.feasible is False
    assert any(issue.code == "tyre_life" for issue in plan.infeasibilities)
    assert "exceeds" in plan.infeasibilities[-1].message


def test_starting_fuel_above_the_tank_fails_before_fuel_used() -> None:
    setup = _setup(
        cars=[
            _car(
                fuel_capacity_kg=110.0,
                starting_fuel_kg=120.0,
                fuel_consumption_kg_per_lap=1.0,
            )
        ]
    )

    plan = score_stints(setup, [StintRequest("HARD", 6), StintRequest("SOFT", 4)])

    assert plan.feasible is False
    assert any(issue.code == "fuel_capacity" for issue in plan.infeasibilities)
    assert any("120.000 kg" in issue.message for issue in plan.infeasibilities)
    assert any("110.000 kg tank" in issue.message for issue in plan.infeasibilities)


def test_a_dry_race_does_not_let_a_wet_tyre_skip_the_compound_rule() -> None:
    compounds = [
        CompoundSpec("SOFT", "Soft", True, "FF1E00", 4, -1.0, 0.0),
        CompoundSpec("HARD", "Hard", True, "F0F0F0", 10, 0.0, 0.0),
        CompoundSpec("INTERMEDIATE", "Intermediate", False, "43B02A", 8, -2.0, 0.0),
    ]
    dry = _setup(compounds=compounds)

    plan = best_f1_plan(dry)
    dodged = score_stints(
        dry, [StintRequest("INTERMEDIATE", 8), StintRequest("HARD", 2)]
    )
    wet = best_f1_plan(_setup(dry_race=False, compounds=compounds))
    hard_only = score_stints(dry, [StintRequest("HARD", 10)])

    assert plan.feasible is True
    assert plan.compounds_used == ["HARD", "SOFT"]
    assert plan.stint_laps == [6, 4]
    assert plan.race_time_sec == 1016.0
    assert plan.why == (
        "A dry race in this rule file needs at least 2 different tyre types. "
        "This plan uses Hard and Soft. "
        "Every stint stays within the tyre life in the file."
    )
    assert dodged.feasible is False
    assert any(issue.code == "compound_rule" for issue in dodged.infeasibilities)
    assert "Intermediate or Wet" in dodged.infeasibilities[0].message
    assert wet.feasible is True
    assert wet.compounds_used == ["INTERMEDIATE", "INTERMEDIATE"]
    assert "wet-weather" in wet.why
    assert hard_only.feasible is False
    assert any(issue.code == "compound_rule" for issue in hard_only.infeasibilities)


def test_fuel_that_cannot_finish_the_race_is_refused() -> None:
    setup = _setup(cars=[_car(fuel_consumption_kg_per_lap=3.0)])

    plan = best_f1_plan(setup)

    assert plan.feasible is False
    assert any(issue.code == "fuel_range" for issue in plan.infeasibilities)
    assert "30.000 kg" in plan.infeasibilities[0].message or any(
        "30.000 kg" in issue.message for issue in plan.infeasibilities
    )


def test_refuelling_flag_points_at_the_endurance_planner() -> None:
    plan = best_f1_plan(_setup(refuelling_allowed=True))

    assert plan.feasible is False
    assert plan.infeasibilities[0].code == "refuel_not_modelled"
    assert "endurance" in plan.infeasibilities[0].message


def test_time_limit_rejects_a_plan_that_cannot_finish() -> None:
    plan = score_stints(
        _setup(time_limit_sec=10),
        [StintRequest("HARD", 7), StintRequest("SOFT", 3)],
    )

    assert plan.feasible is False
    assert any(issue.code == "time_limit" for issue in plan.infeasibilities)


def test_no_sequence_when_stops_cannot_satisfy_the_compound_rule() -> None:
    plan = best_f1_plan(_setup(max_stops=0))

    assert plan.feasible is False
    assert plan.infeasibilities[0].code == "no_legal_plan"


def test_stop_search_wider_than_four_is_refused() -> None:
    plan = best_f1_plan(_setup(max_stops=5))

    assert plan.infeasibilities[0].code == "stop_search_too_wide"


def test_wet_race_can_be_a_single_intermediate_stint() -> None:
    setup = _setup(
        dry_race=False,
        compounds=[
            CompoundSpec("INTERMEDIATE", "Intermediate", False, "43B02A", 10, 0.0, 0.0)
        ],
        max_stops=1,
    )

    plan = best_f1_plan(setup)

    assert plan.feasible is True
    assert plan.pit_stops == 0
    assert plan.stint_laps == [10]
    assert plan.race_time_sec == 1000.0
    assert "wet" in plan.why


def test_compare_ranks_a_slower_named_plan_behind_the_suggestion() -> None:
    ranked = compare_f1(
        _setup(),
        [
            ScenarioRequest(
                "Short soft",
                (StintRequest("SOFT", 2), StintRequest("HARD", 8)),
            )
        ],
    )

    assert [plan.strategy_name for plan in ranked] == ["Suggested", "Short soft"]
    assert ranked[0].preferred is True
    assert ranked[0].race_time_sec == 1016.0
    assert ranked[1].race_time_sec == 1018.0
    assert ranked[0].ranking_reason == "Fastest legal plan under this file."
    assert ranked[1].ranking_reason == "Slower than the leading legal plan by 2.000 s."


def test_safety_car_moves_the_stop_into_a_later_window() -> None:
    plan = best_f1_plan(_setup())
    result = replan_f1_safety_car(
        plan,
        SafetyCarRequest(
            start_lap=7, end_lap=8, pit_loss_sec=8.0, pull_pit_into_sc=True
        ),
    )

    assert result.original_race_time_sec == 1016.0
    assert result.replanned_race_time_sec == 1005.0
    assert result.time_saved_sec == 11.0
    assert result.stop_laps == [7]
    assert result.stops_moved is True
    assert "Move a stop to lap 7" in result.summary
    assert "11.000 s" in result.summary
    assert "not resimulated" in result.confidence


def test_safety_car_can_keep_the_stop_and_only_reprice_it() -> None:
    plan = best_f1_plan(_setup())
    result = replan_f1_safety_car(
        plan,
        SafetyCarRequest(
            start_lap=6, end_lap=8, pit_loss_sec=8.0, pull_pit_into_sc=False
        ),
    )

    assert result.replanned_race_time_sec == 1004.0
    assert result.time_saved_sec == 12.0
    assert result.stop_laps == [6]
    assert result.stops_moved is False
    assert "Pit on lap 6" in result.summary
    assert "saving 12.000 s" in result.summary
    assert "stays the same" in result.summary


def test_safety_car_outside_tyre_life_saves_nothing() -> None:
    plan = best_f1_plan(_setup())
    result = replan_f1_safety_car(
        plan,
        SafetyCarRequest(start_lap=3, end_lap=4, pit_loss_sec=8.0),
    )

    assert result.replanned_race_time_sec == 1016.0
    assert result.time_saved_sec == 0.0
    assert result.stops_moved is False
    assert "Estimated time saved: 0 s." in result.summary


def test_safety_car_window_outside_the_race_is_not_applied() -> None:
    plan = best_f1_plan(_setup())
    result = replan_f1_safety_car(
        plan, SafetyCarRequest(start_lap=0, end_lap=2, pit_loss_sec=8)
    )

    assert result.time_saved_sec == 0.0
    assert "window was 0–2" in result.summary
    assert result.confidence == "Not evaluated"


def test_hard_then_soft_window_is_laps_six_to_nine() -> None:
    assert legal_one_stop_window(_setup(), "HARD", "SOFT") == (6, 9)
    assert legal_one_stop_window(_setup(), "SOFT", "SOFT") is None


def test_safety_car_field_loss_hits_both_clocks_and_a_rival_stop_cancels_the_saving() -> (
    None
):
    plan = best_f1_plan(_setup())
    field = replan_f1_safety_car(
        plan,
        SafetyCarRequest(
            start_lap=6,
            end_lap=8,
            pit_loss_sec=8.0,
            pull_pit_into_sc=False,
            field_lap_delta_sec=2.0,
        ),
    )
    rival = replan_f1_safety_car(
        plan,
        SafetyCarRequest(
            start_lap=6,
            end_lap=8,
            pit_loss_sec=8.0,
            pull_pit_into_sc=False,
            rival_stops=1,
        ),
    )
    refused = replan_f1_safety_car(
        plan,
        SafetyCarRequest(start_lap=6, end_lap=8, pit_loss_sec=-1.0),
    )

    assert field.original_race_time_sec == 1022.0
    assert field.replanned_race_time_sec == 1010.0
    assert field.time_saved_sec == 12.0
    assert "saving 12.000 s" in field.summary
    assert "both clocks" in field.summary
    assert rival.time_saved_sec == 0.0
    assert "saving 12.000 s" in rival.summary
    assert "net saving against that rival is 0.000 s" in rival.summary
    assert "not resimulated" in field.confidence
    assert refused.confidence == "Not evaluated"
    assert "must be zero or higher" in refused.summary
    assert "window was" not in refused.summary
