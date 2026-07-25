"""Trigger cards must be complete, deterministic, and honest about their source."""

from __future__ import annotations

import pytest

from engine.planner import DEFAULT_PRESET, compute_plan, load_preset
from engine.simulation import default_uncertainty
from engine.strategy import compare_strategies
from engine.trigger_cards import (
    HOLD,
    MANUAL_SOURCE,
    PRE_RACE_NOTICE,
    RECONSIDER,
    TELEMETRY_SOURCE,
    TriggerObservation,
    build_trigger_cards,
    trigger_cards_markdown,
    trigger_cards_payload,
)

REQUIRED_FIELDS = {
    "id",
    "name",
    "source",
    "metric",
    "unit",
    "threshold_low",
    "threshold_high",
    "current_value",
    "affected_decision",
    "action_hold",
    "action_reconsider",
    "status",
}

EXPECTED_IDS = [
    "FUEL_BURN_HIGH",
    "FUEL_BURN_LOW",
    "PACE_SLOW",
    "PACE_FAST",
    "TYRE_LIFE_LOW",
    "SAFETY_CAR_WINDOW",
]


@pytest.fixture(scope="module")
def baseline():
    config = load_preset(DEFAULT_PRESET)
    plan = compute_plan(config)
    uncertainty = default_uncertainty(config)
    return plan, uncertainty


def test_six_trigger_types_with_all_fields(baseline):
    plan, uncertainty = baseline
    cards = build_trigger_cards(plan, uncertainty)
    assert [card.id for card in cards] == EXPECTED_IDS
    for card in cards:
        payload = card.to_dict()
        assert REQUIRED_FIELDS <= set(payload)
        assert payload["status"] in {HOLD, RECONSIDER}
        assert payload["affected_decision"]
        assert payload["action_hold"] and payload["action_reconsider"]
        assert payload["unit"]


def test_manual_inputs_are_labelled_manual_and_hold(baseline):
    plan, uncertainty = baseline
    cards = build_trigger_cards(plan, uncertainty)
    assert {card.source for card in cards} == {MANUAL_SOURCE}
    assert all(card.status == HOLD for card in cards)


def test_telemetry_calibrated_cards_are_labelled_telemetry(baseline):
    plan, uncertainty = baseline
    cards = build_trigger_cards(plan, uncertainty, telemetry_calibrated=True)
    assert {card.source for card in cards} == {TELEMETRY_SOURCE}


def test_fuel_burn_above_range_flips_to_reconsider(baseline):
    plan, uncertainty = baseline
    high = max(uncertainty.fuel_p10_l_per_lap, uncertainty.fuel_p90_l_per_lap)
    cards = {
        card.id: card
        for card in build_trigger_cards(
            plan,
            uncertainty,
            TriggerObservation(fuel_burn_per_lap=high + 0.5),
        )
    }
    assert cards["FUEL_BURN_HIGH"].status == RECONSIDER
    assert cards["FUEL_BURN_LOW"].status == HOLD
    assert cards["FUEL_BURN_HIGH"].action == cards["FUEL_BURN_HIGH"].action_reconsider


def test_fuel_burn_below_range_flips_to_reconsider(baseline):
    plan, uncertainty = baseline
    low = min(uncertainty.fuel_p10_l_per_lap, uncertainty.fuel_p90_l_per_lap)
    cards = {
        card.id: card
        for card in build_trigger_cards(
            plan,
            uncertainty,
            TriggerObservation(fuel_burn_per_lap=max(low - 0.5, 0.01)),
        )
    }
    assert cards["FUEL_BURN_LOW"].status == RECONSIDER
    assert cards["FUEL_BURN_HIGH"].status == HOLD


def test_pace_thresholds_cross_in_both_directions(baseline):
    plan, uncertainty = baseline
    low = min(uncertainty.pace_p10_sec, uncertainty.pace_p90_sec)
    high = max(uncertainty.pace_p10_sec, uncertainty.pace_p90_sec)
    slow = {
        card.id: card
        for card in build_trigger_cards(
            plan, uncertainty, TriggerObservation(green_lap_time_sec=high + 5)
        )
    }
    fast = {
        card.id: card
        for card in build_trigger_cards(
            plan, uncertainty, TriggerObservation(green_lap_time_sec=low - 5)
        )
    }
    assert slow["PACE_SLOW"].status == RECONSIDER
    assert slow["PACE_FAST"].status == HOLD
    assert fast["PACE_FAST"].status == RECONSIDER
    assert fast["PACE_SLOW"].status == HOLD
    assert slow["PACE_SLOW"].action == slow["PACE_SLOW"].action_reconsider
    assert fast["PACE_SLOW"].action == fast["PACE_SLOW"].action_hold


def test_tyre_life_below_longest_planned_run_reconsiders(baseline):
    plan, uncertainty = baseline
    longest = max(stint.tyre_age_at_end_laps for stint in plan.stints)
    card = next(
        card
        for card in build_trigger_cards(
            plan, uncertainty, TriggerObservation(tyre_life_laps=longest - 1)
        )
        if card.id == "TYRE_LIFE_LOW"
    )
    assert card.status == RECONSIDER
    assert card.threshold_low == float(longest)


def test_safety_car_window_overlapping_a_planned_stop_reconsiders(baseline):
    plan, uncertainty = baseline
    stop_min = plan.stints[0].end_min
    overlapping = next(
        card
        for card in build_trigger_cards(
            plan,
            uncertainty,
            TriggerObservation(safety_car_window_min=(stop_min - 5, stop_min + 5)),
        )
        if card.id == "SAFETY_CAR_WINDOW"
    )
    clear = next(
        card
        for card in build_trigger_cards(
            plan,
            uncertainty,
            TriggerObservation(safety_car_window_min=(0.0, 0.5)),
        )
        if card.id == "SAFETY_CAR_WINDOW"
    )
    assert overlapping.status == RECONSIDER
    assert clear.status == HOLD
    assert any("PRE-RACE WHAT-IF ONLY" in note for note in overlapping.notes)


def test_undeclared_safety_car_window_holds_and_says_so(baseline):
    plan, uncertainty = baseline
    card = next(
        card
        for card in build_trigger_cards(plan, uncertainty)
        if card.id == "SAFETY_CAR_WINDOW"
    )
    assert card.status == HOLD
    assert "No Safety Car window declared." in card.notes


def test_payload_and_markdown_render_every_card(baseline):
    plan, uncertainty = baseline
    payload = trigger_cards_payload(plan, uncertainty)
    assert len(payload) == len(EXPECTED_IDS)
    markdown = "\n".join(trigger_cards_markdown(payload))
    assert PRE_RACE_NOTICE in markdown
    for card in payload:
        assert card["name"] in markdown


def test_cards_are_built_from_the_recommended_comparison_plan():
    config = load_preset(DEFAULT_PRESET)
    comparison = compare_strategies(config, iterations=20)
    cards = build_trigger_cards(comparison.preferred.plan, comparison.uncertainty)
    assert [card.id for card in cards] == EXPECTED_IDS


def test_plan_without_stints_still_produces_cards():
    config = load_preset(DEFAULT_PRESET)
    plan = compute_plan(config)
    uncertainty = default_uncertainty(config)
    plan.stints = []
    cards = build_trigger_cards(plan, uncertainty)
    tyre = next(card for card in cards if card.id == "TYRE_LIFE_LOW")
    safety_car = next(card for card in cards if card.id == "SAFETY_CAR_WINDOW")
    assert tyre.threshold_low == 0.0
    assert safety_car.current_value == 0.0
