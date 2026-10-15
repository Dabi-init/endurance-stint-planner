"""Versioned F1 files, entry-list merge, and user overrides."""

from __future__ import annotations

import pytest

from engine.f1 import readiness_gaps
from engine.series_config import (
    EntryDriver,
    EntryList,
    EntryTeam,
    apply_overrides,
    colour_css,
    load_season_document,
    load_setup,
    setup_from_dict,
    setup_to_dict,
)

HEADSHOT = (
    "https://media.formula1.com/d_driver_fallback_image.png/content/dam/"
    "fom-website/drivers/M/MAXVER01_Max_Verstappen/maxver01.png.transform/1col/image.png"
)


def _entry() -> EntryList:
    return EntryList(
        season=2024,
        round=1,
        event_name="Bahrain Grand Prix",
        drivers=(
            EntryDriver(
                code="VER",
                driver_number=1,
                full_name="Max VERSTAPPEN",
                team_name="Red Bull Racing",
                team_colour="3671c6",
                headshot_url=HEADSHOT,
                country_code="NED",
            ),
        ),
        teams=(EntryTeam("Red Bull Racing", "3671c6", None),),
        source_name="openf1",
        terms="recorded fixture terms",
    )


def test_bundled_2024_bahrain_uses_season_rules_and_event_numbers() -> None:
    setup = load_setup(2024, 1)

    season_doc, season_label = load_season_document(2024)

    assert setup.schema_version == 1
    assert season_doc["schema_version"] == 1
    assert season_label == "season"
    assert setup.refuelling_allowed is False
    assert setup.dry_min_compounds == 2
    assert setup.race_laps == 57
    assert setup.pit_lane_loss_sec == 22.0
    assert setup.provenance["refuelling_allowed"] == "season"
    assert setup.provenance["pit_lane_loss_sec"] == "event"
    assert setup.provenance["compounds.SOFT.max_laps"] == "event"
    assert setup.compound("SOFT").max_laps == 22
    assert any("Entry list was not refreshed." in note for note in setup.assumptions)


def test_resolved_setup_round_trips() -> None:
    setup = load_setup(2024, 1)
    again = setup_from_dict(setup_to_dict(setup))

    assert again.race_laps == 57
    assert again.pit_lane_loss_sec == 22.0
    assert again.refuelling_allowed is False
    assert [
        compound.compound_id for compound in again.compounds if compound.max_laps
    ] == [
        "SOFT",
        "MEDIUM",
        "HARD",
    ]


def test_user_overrides_beat_the_fetched_entry_list() -> None:
    setup = load_setup(
        2024,
        1,
        entry=_entry(),
        overrides={
            "pit_lane_loss_sec": 21.0,
            "drivers": [{"code": "VER", "pace_delta_sec": -0.2}],
            "teams": [
                {
                    "team_name": "Red Bull Racing",
                    "livery_image_url": "https://example.test/livery.png",
                }
            ],
            "cars": [
                {
                    "car_id": "assumption-car",
                    "upgrades": [
                        {
                            "upgrade_id": "floor",
                            "pace_delta_sec": -0.1,
                            "note": "user assumption",
                        }
                    ],
                }
            ],
        },
    )
    driver = setup.drivers[0]
    team = setup.teams[0]

    assert setup.pit_lane_loss_sec == 21.0
    assert setup.provenance["pit_lane_loss_sec"] == "user"
    assert driver.headshot_url == HEADSHOT
    assert driver.team_colour == "3671c6"
    assert driver.pace_delta_sec == -0.2
    assert setup.provenance["drivers.VER.headshot_url"] == "fetched"
    assert setup.provenance["drivers.VER.pace_delta_sec"] == "user"
    assert team.livery_image_url == "https://example.test/livery.png"
    assert setup.provenance["teams.Red Bull Racing.livery_image_url"] == "user"
    assert setup.cars[0].upgrades[0].upgrade_id == "floor"
    assert setup.provenance["cars.assumption-car.upgrades"] == "user"
    assert colour_css(driver.team_colour) == "#3671c6"
    assert colour_css("not-a-colour") is None


def test_apply_overrides_keeps_unmentioned_fields() -> None:
    setup = load_setup(2024, 1, entry=_entry())
    updated = apply_overrides(setup, {"base_lap_time_sec": 95.529})

    assert updated.base_lap_time_sec == 95.529
    assert updated.provenance["base_lap_time_sec"] == "user"
    assert updated.drivers[0].headshot_url == HEADSHOT
    assert updated.provenance["drivers.VER.headshot_url"] == "fetched"
    assert updated.race_laps == 57


def test_missing_season_uses_the_latest_bundled_template() -> None:
    setup = load_setup(2030, 1)

    assert setup.refuelling_allowed is False
    assert setup.provenance["refuelling_allowed"] == "season-template-2025"
    assert any(
        "No 2030 season file" in note and "2025" in note for note in setup.assumptions
    )
    messages = [message for _code, message in readiness_gaps(setup)]
    assert "Add the race distance in laps." in messages


def test_colour_helper_accepts_a_leading_hash() -> None:
    assert colour_css("#3671C6") == "#3671C6"


def test_season_outside_the_calendar_range_is_refused() -> None:
    with pytest.raises(ValueError, match="1950 to 2100"):
        load_setup(1800, 1)
