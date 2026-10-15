"""Load versioned F1 season and event files and merge user overrides.

Rules, car specs, driver pace, and team upgrades are data. A fetched entry
list fills names, numbers, team colours, and headshot URLs. User keys win.
Bundled files are never rewritten by a refresh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.f1 import (
    CarSpec,
    CompoundSpec,
    DriverSpec,
    F1Setup,
    TeamSpec,
    UpgradeSpec,
)

IMAGE_POLICY = (
    "headshot_url, team_colour, and livery_image_url are references only. "
    "Pitwall does not download or store image files. "
    "OpenF1 may supply headshot_url and team_colour. "
    "A livery image is used only when you or a source provide a URL."
)

_EVENT_FIELDS = (
    "event_name",
    "circuit_id",
    "race_laps",
    "dry_race",
    "time_limit_sec",
    "pit_lane_loss_sec",
    "base_lap_time_sec",
    "evidence_level",
    "data_source",
    "focus_driver",
)
_COMPOUND_PERF = ("max_laps", "pace_delta_sec", "deg_sec_per_lap")
_CAR_FIELDS = (
    "team_name",
    "team_colour",
    "livery_image_url",
    "pace_delta_sec",
    "fuel_capacity_kg",
    "fuel_consumption_kg_per_lap",
    "starting_fuel_kg",
)
_DRIVER_IDENTITY = (
    "driver_number",
    "full_name",
    "first_name",
    "last_name",
    "team_name",
    "team_colour",
    "headshot_url",
    "country_code",
    "pace_delta_sec",
    "car_id",
)


@dataclass(frozen=True)
class EntryDriver:
    code: str
    driver_number: int | None
    full_name: str
    team_name: str
    team_colour: str | None
    headshot_url: str | None
    country_code: str | None = None
    first_name: str = ""
    last_name: str = ""


@dataclass(frozen=True)
class EntryTeam:
    team_name: str
    team_colour: str | None = None
    livery_image_url: str | None = None


@dataclass(frozen=True)
class EntryList:
    season: int
    round: int
    event_name: str
    drivers: tuple[EntryDriver, ...]
    teams: tuple[EntryTeam, ...]
    source_name: str
    terms: str


def series_root() -> Path:
    return Path(__file__).resolve().parent / "series_data" / "f1"


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _version(doc: dict[str, Any], label: str) -> None:
    version = doc.get("schema_version", 1)
    if version != 1:
        raise ValueError(f"{label} schema_version must be 1")


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{label} must be an integer")


def _as_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{label} must be a finite number")
    return number


def _as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _calendar_year(season: int) -> int:
    """Keep a season number inside a fixed range before it is used as a label."""
    if isinstance(season, bool) or not isinstance(season, int):
        raise ValueError("season must be an integer")
    if season < 1950 or season > 2100:
        raise ValueError("season must be from 1950 to 2100")
    return season


def _season_files(folder: Path) -> dict[int, Path]:
    """Map bundled season files. The path always comes from this directory listing."""
    if not folder.is_dir():
        return {}
    found: dict[int, Path] = {}
    for path in folder.glob("*.json"):
        if path.stem.isdigit():
            found[int(path.stem)] = path
    return found


def load_season_document(
    season: int, root: Path | None = None
) -> tuple[dict[str, Any], str]:
    year = _calendar_year(season)
    folder = (root or series_root()) / "seasons"
    files = _season_files(folder)
    if not files:
        raise ValueError(f"No F1 season files in {folder}")
    exact = files.get(year)
    if exact is not None:
        return json.loads(exact.read_text(encoding="utf-8")), "season"
    years = sorted(files)
    prior = [item for item in years if item <= year]
    chosen = prior[-1] if prior else years[-1]
    return (
        json.loads(files[chosen].read_text(encoding="utf-8")),
        f"season-template-{chosen}",
    )


def load_event_document(
    season: int,
    round_: int,
    root: Path | None = None,
) -> dict[str, Any] | None:
    folder = (root or series_root()) / "events"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if (
            int(document.get("season", -1)) == season
            and int(document.get("round", -1)) == round_
        ):
            return document
    return None


def load_setup(
    season: int,
    round_: int,
    *,
    entry: EntryList | None = None,
    overrides: dict[str, Any] | None = None,
    root: Path | None = None,
) -> F1Setup:
    season_doc, source = load_season_document(season, root)
    event_doc = load_event_document(season, round_, root)
    return resolve_setup(
        season_doc,
        event_doc,
        entry,
        overrides,
        season=season,
        round_=round_,
        season_source=source,
    )


def resolve_setup(
    season_doc: dict[str, Any],
    event_doc: dict[str, Any] | None,
    entry: EntryList | None,
    overrides: dict[str, Any] | None,
    *,
    season: int,
    round_: int,
    season_source: str,
) -> F1Setup:
    """Merge season < event < fetched entry list < user overrides."""
    season_body = _object(season_doc, "season")
    _version(season_body, "season")
    event_body = _object(event_doc, "event") if event_doc is not None else None
    if event_body is not None:
        _version(event_body, "event")
    user = _object(overrides or {}, "overrides")
    _version(user, "overrides") if "schema_version" in user else None

    resolved: dict[str, Any] = {
        "schema_version": 1,
        "series": "f1",
        "season": season,
        "round": round_,
        "event_name": f"Round {round_}",
        "circuit_id": "",
        "race_laps": None,
        "dry_race": True,
        "time_limit_sec": None,
        "pit_lane_loss_sec": None,
        "base_lap_time_sec": None,
        "refuelling_allowed": False,
        "dry_min_compounds": 2,
        "wet_min_compounds": 1,
        "max_stops": 3,
        "evidence_level": str(season_body.get("evidence_level", "C")),
        "data_source": "No event file for this round yet.",
        "focus_driver": None,
        "compounds": [],
        "cars": [],
        "drivers": [],
        "teams": [],
        "provenance": {},
        "assumptions": [],
    }
    provenance: dict[str, str] = resolved["provenance"]
    assumptions: list[str] = resolved["assumptions"]
    if season_source != "season":
        template_year = season_source.removeprefix("season-template-")
        assumptions.append(
            f"No {season} season file is bundled. Rule shape comes from {template_year}. "
            "Confirm the sporting rules before you use them."
        )
    if isinstance(season_body.get("notes"), str) and season_body["notes"].strip():
        assumptions.append(season_body["notes"].strip())

    rules = _object(season_body.get("rules", {}), "season.rules")
    _apply_rules(resolved, rules, season_source)
    _apply_catalogue(resolved, season_body.get("compounds", []), season_source)
    if event_body is not None:
        _apply_rules(
            resolved, _object(event_body.get("rules", {}), "event.rules"), "event"
        )
        _apply_event_fields(resolved, event_body, "event")
        _apply_compound_perf(resolved, event_body.get("compounds"), "event")
        _merge_cars(resolved, event_body.get("cars", []), "event")
        _merge_drivers(resolved, event_body.get("drivers", []), "event")
        _merge_teams(resolved, event_body.get("teams", []), "event")
    if entry is not None:
        assumptions.append(
            f"Entry list refreshed from {entry.source_name}. {entry.terms}"
        )
        if resolved["event_name"] == f"Round {round_}" and entry.event_name:
            resolved["event_name"] = entry.event_name
            provenance["event_name"] = "fetched"
        _merge_drivers(
            resolved,
            [_entry_driver_dict(driver) for driver in entry.drivers],
            "fetched",
        )
        _merge_teams(
            resolved, [_entry_team_dict(team) for team in entry.teams], "fetched"
        )
    else:
        assumptions.append("Entry list was not refreshed.")

    _apply_rules(resolved, _object(user.get("rules", {}), "overrides.rules"), "user")
    _apply_event_fields(resolved, user, "user")
    _apply_compound_perf(resolved, user.get("compounds"), "user")
    _merge_cars(resolved, user.get("cars", []), "user")
    _merge_drivers(resolved, user.get("drivers", []), "user")
    _merge_teams(resolved, user.get("teams", []), "user")
    _ensure_default_car(resolved, season_body.get("car_defaults"), season_source)
    return setup_from_dict(resolved)


def apply_overrides(setup: F1Setup, overrides: dict[str, Any] | None) -> F1Setup:
    """Apply a partial resolved document. Only keys that are present change."""
    if not overrides:
        return setup
    document = setup_to_dict(setup)
    user = _object(overrides, "overrides")
    _apply_rules(document, _object(user.get("rules", {}), "overrides.rules"), "user")
    _apply_event_fields(document, user, "user")
    _apply_compound_perf(document, user.get("compounds"), "user")
    _merge_cars(document, user.get("cars", []), "user")
    _merge_drivers(document, user.get("drivers", []), "user")
    _merge_teams(document, user.get("teams", []), "user")
    return setup_from_dict(document)


def setup_to_dict(setup: F1Setup) -> dict[str, Any]:
    return {
        "schema_version": setup.schema_version,
        "series": "f1",
        "season": setup.season,
        "round": setup.round,
        "event_name": setup.event_name,
        "circuit_id": setup.circuit_id,
        "race_laps": setup.race_laps,
        "dry_race": setup.dry_race,
        "time_limit_sec": setup.time_limit_sec,
        "pit_lane_loss_sec": setup.pit_lane_loss_sec,
        "base_lap_time_sec": setup.base_lap_time_sec,
        "refuelling_allowed": setup.refuelling_allowed,
        "dry_min_compounds": setup.dry_min_compounds,
        "wet_min_compounds": setup.wet_min_compounds,
        "max_stops": setup.max_stops,
        "evidence_level": setup.evidence_level,
        "data_source": setup.data_source,
        "focus_driver": setup.focus_driver,
        "compounds": [
            {
                "id": compound.compound_id,
                "label": compound.label,
                "dry": compound.dry,
                "colour": compound.colour,
                "max_laps": compound.max_laps,
                "pace_delta_sec": compound.pace_delta_sec,
                "deg_sec_per_lap": compound.deg_sec_per_lap,
            }
            for compound in setup.compounds
        ],
        "cars": [_car_dict(car) for car in setup.cars],
        "drivers": [_driver_dict(driver) for driver in setup.drivers],
        "teams": [
            {
                "team_name": team.team_name,
                "team_colour": team.team_colour,
                "livery_image_url": team.livery_image_url,
            }
            for team in setup.teams
        ],
        "provenance": dict(setup.provenance),
        "assumptions": list(setup.assumptions),
    }


def setup_from_dict(document: dict[str, Any]) -> F1Setup:
    body = _object(document, "setup")
    compounds = [_compound_from_dict(row) for row in body.get("compounds", [])]
    return F1Setup(
        schema_version=int(body.get("schema_version", 1)),
        season=_as_int(body.get("season"), "season"),
        round=_as_int(body.get("round"), "round"),
        event_name=str(body.get("event_name") or ""),
        circuit_id=str(body.get("circuit_id") or ""),
        race_laps=_optional_int(body.get("race_laps"), "race_laps"),
        dry_race=_as_bool(body.get("dry_race", True), "dry_race"),
        time_limit_sec=_optional_float(body.get("time_limit_sec"), "time_limit_sec"),
        pit_lane_loss_sec=_optional_float(
            body.get("pit_lane_loss_sec"), "pit_lane_loss_sec"
        ),
        base_lap_time_sec=_optional_float(
            body.get("base_lap_time_sec"), "base_lap_time_sec"
        ),
        refuelling_allowed=_as_bool(
            body.get("refuelling_allowed", False), "refuelling_allowed"
        ),
        dry_min_compounds=_as_int(
            body.get("dry_min_compounds", 2), "dry_min_compounds"
        ),
        wet_min_compounds=_as_int(
            body.get("wet_min_compounds", 1), "wet_min_compounds"
        ),
        max_stops=_as_int(body.get("max_stops", 3), "max_stops"),
        compounds=compounds,
        cars=[_car_from_dict(row) for row in body.get("cars", [])],
        drivers=[_driver_from_dict(row) for row in body.get("drivers", [])],
        teams=[_team_from_dict(row) for row in body.get("teams", [])],
        focus_driver=_optional_code(body.get("focus_driver")),
        evidence_level=str(body.get("evidence_level") or "C"),
        data_source=str(body.get("data_source") or ""),
        provenance={
            str(key): str(value) for key, value in body.get("provenance", {}).items()
        },
        assumptions=[str(item) for item in body.get("assumptions", [])],
    )


def colour_css(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip().lstrip("#")
    if len(raw) == 6 and all(char in "0123456789abcdefABCDEF" for char in raw):
        return f"#{raw}"
    return None


def _apply_rules(resolved: dict[str, Any], rules: dict[str, Any], source: str) -> None:
    if not rules:
        return
    provenance: dict[str, str] = resolved["provenance"]
    if "refuelling_allowed" in rules:
        resolved["refuelling_allowed"] = _as_bool(
            rules["refuelling_allowed"], "refuelling_allowed"
        )
        provenance["refuelling_allowed"] = source
    for key in ("dry_min_compounds", "wet_min_compounds", "max_stops"):
        if key in rules:
            resolved[key] = _as_int(rules[key], key)
            provenance[key] = source


def _apply_event_fields(
    resolved: dict[str, Any], body: dict[str, Any], source: str
) -> None:
    provenance: dict[str, str] = resolved["provenance"]
    for key in _EVENT_FIELDS:
        if key not in body:
            continue
        value = body[key]
        if key in {"race_laps"}:
            resolved[key] = _optional_int(value, key)
        elif key in {"time_limit_sec", "pit_lane_loss_sec", "base_lap_time_sec"}:
            resolved[key] = _optional_float(value, key)
        elif key == "dry_race":
            resolved[key] = _as_bool(value, key)
        elif key == "focus_driver":
            resolved[key] = _optional_code(value)
        elif value is None:
            resolved[key] = None
        else:
            resolved[key] = str(value)
        provenance[key] = source


def _apply_catalogue(resolved: dict[str, Any], rows: Any, source: str) -> None:
    if not isinstance(rows, list):
        raise ValueError("season compounds must be a JSON array")
    compounds: list[dict[str, Any]] = []
    provenance: dict[str, str] = resolved["provenance"]
    for row in rows:
        body = _object(row, "compound")
        compound_id = str(body.get("id", "")).upper()
        if not compound_id:
            raise ValueError("compound id is required")
        compounds.append(
            {
                "id": compound_id,
                "label": str(body.get("label") or compound_id.title()),
                "dry": _as_bool(body.get("dry", True), f"{compound_id}.dry"),
                "colour": str(body.get("colour") or ""),
                "max_laps": None,
                "pace_delta_sec": 0.0,
                "deg_sec_per_lap": 0.0,
            }
        )
        provenance[f"compounds.{compound_id}.label"] = source
        provenance[f"compounds.{compound_id}.pace_delta_sec"] = "default"
        provenance[f"compounds.{compound_id}.deg_sec_per_lap"] = "default"
    resolved["compounds"] = compounds


def _apply_compound_perf(resolved: dict[str, Any], raw: Any, source: str) -> None:
    if raw is None:
        return
    provenance: dict[str, str] = resolved["provenance"]
    if isinstance(raw, list):
        resolved["compounds"] = []
        _apply_catalogue(resolved, raw, source)
        return
    if not isinstance(raw, dict):
        raise ValueError("compounds must be a JSON object or array")
    by_id = {row["id"]: row for row in resolved["compounds"]}
    for key, perf in raw.items():
        compound_id = str(key).upper()
        body = _object(perf, compound_id)
        row = by_id.get(compound_id)
        if row is None:
            row = {
                "id": compound_id,
                "label": str(body.get("label") or compound_id.title()),
                "dry": _as_bool(body.get("dry", True), f"{compound_id}.dry"),
                "colour": str(body.get("colour") or ""),
                "max_laps": None,
                "pace_delta_sec": 0.0,
                "deg_sec_per_lap": 0.0,
            }
            resolved["compounds"].append(row)
            by_id[compound_id] = row
            provenance[f"compounds.{compound_id}.label"] = source
        for field in _COMPOUND_PERF:
            if field not in body:
                continue
            if field == "max_laps":
                row[field] = _optional_int(body[field], f"{compound_id}.{field}")
            else:
                row[field] = _as_float(body[field], f"{compound_id}.{field}")
            provenance[f"compounds.{compound_id}.{field}"] = source
        if "label" in body:
            row["label"] = str(body["label"])
            provenance[f"compounds.{compound_id}.label"] = source
        if "dry" in body:
            row["dry"] = _as_bool(body["dry"], f"{compound_id}.dry")


def _merge_cars(resolved: dict[str, Any], rows: Any, source: str) -> None:
    if not rows:
        return
    if not isinstance(rows, list):
        raise ValueError("cars must be a JSON array")
    by_id = {row["car_id"]: row for row in resolved["cars"]}
    provenance: dict[str, str] = resolved["provenance"]
    for raw in rows:
        body = _object(raw, "car")
        car_id = str(body.get("car_id") or "")
        if not car_id:
            raise ValueError("car_id is required")
        row = by_id.get(car_id)
        if row is None:
            row = {"car_id": car_id, "upgrades": []}
            resolved["cars"].append(row)
            by_id[car_id] = row
        for field in _CAR_FIELDS:
            if field not in body:
                continue
            value = body[field]
            if field in {
                "pace_delta_sec",
                "fuel_capacity_kg",
                "fuel_consumption_kg_per_lap",
                "starting_fuel_kg",
            }:
                row[field] = (
                    None if value is None else _as_float(value, f"{car_id}.{field}")
                )
            else:
                row[field] = None if value is None else str(value)
            provenance[f"cars.{car_id}.{field}"] = source
        if "upgrades" in body:
            upgrades = body["upgrades"] or []
            if not isinstance(upgrades, list):
                raise ValueError("upgrades must be a JSON array")
            row["upgrades"] = [_upgrade_dict(item) for item in upgrades]
            provenance[f"cars.{car_id}.upgrades"] = source


def _merge_drivers(resolved: dict[str, Any], rows: Any, source: str) -> None:
    if not rows:
        return
    if not isinstance(rows, list):
        raise ValueError("drivers must be a JSON array")
    by_code = {row["code"]: row for row in resolved["drivers"]}
    provenance: dict[str, str] = resolved["provenance"]
    for raw in rows:
        body = _object(raw, "driver")
        code = str(body.get("code") or "").upper()
        if not code:
            raise ValueError("driver code is required")
        row = by_code.get(code)
        if row is None:
            row = {"code": code, "pace_delta_sec": 0.0}
            resolved["drivers"].append(row)
            by_code[code] = row
            provenance[f"drivers.{code}.pace_delta_sec"] = "default"
        for field in _DRIVER_IDENTITY:
            if field not in body:
                continue
            value = body[field]
            if field == "driver_number":
                row[field] = _optional_int(value, f"{code}.{field}")
            elif field == "pace_delta_sec":
                row[field] = _as_float(value, f"{code}.{field}")
            elif value is None:
                row[field] = None
            else:
                row[field] = str(value)
            provenance[f"drivers.{code}.{field}"] = source


def _merge_teams(resolved: dict[str, Any], rows: Any, source: str) -> None:
    if not rows:
        return
    if not isinstance(rows, list):
        raise ValueError("teams must be a JSON array")
    by_name = {row["team_name"]: row for row in resolved["teams"]}
    provenance: dict[str, str] = resolved["provenance"]
    for raw in rows:
        body = _object(raw, "team")
        name = str(body.get("team_name") or "")
        if not name:
            raise ValueError("team_name is required")
        row = by_name.get(name)
        if row is None:
            row = {"team_name": name, "team_colour": None, "livery_image_url": None}
            resolved["teams"].append(row)
            by_name[name] = row
        for field in ("team_colour", "livery_image_url"):
            if field not in body:
                continue
            value = body[field]
            row[field] = None if value is None else str(value)
            provenance[f"teams.{name}.{field}"] = source


def _ensure_default_car(
    resolved: dict[str, Any],
    defaults: Any,
    source: str,
) -> None:
    if resolved["cars"] or not isinstance(defaults, dict):
        return
    car = {
        "car_id": "default",
        "team_name": "",
        "team_colour": None,
        "livery_image_url": None,
        "pace_delta_sec": _as_float(
            defaults.get("pace_delta_sec", 0.0), "pace_delta_sec"
        ),
        "fuel_capacity_kg": _optional_float(
            defaults.get("fuel_capacity_kg"), "fuel_capacity_kg"
        ),
        "fuel_consumption_kg_per_lap": _optional_float(
            defaults.get("fuel_consumption_kg_per_lap"),
            "fuel_consumption_kg_per_lap",
        ),
        "starting_fuel_kg": _optional_float(
            defaults.get("starting_fuel_kg"), "starting_fuel_kg"
        ),
        "upgrades": [],
    }
    resolved["cars"].append(car)
    note = defaults.get("note")
    if isinstance(note, str) and note.strip():
        resolved["assumptions"].append(note.strip())
    provenance: dict[str, str] = resolved["provenance"]
    for field in (
        "pace_delta_sec",
        "fuel_capacity_kg",
        "fuel_consumption_kg_per_lap",
        "starting_fuel_kg",
    ):
        provenance[f"cars.default.{field}"] = source


def _optional_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, label)


def _optional_float(value: Any, label: str) -> float | None:
    if value is None:
        return None
    return _as_float(value, label)


def _optional_code(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _entry_driver_dict(driver: EntryDriver) -> dict[str, Any]:
    return {
        "code": driver.code,
        "driver_number": driver.driver_number,
        "full_name": driver.full_name,
        "first_name": driver.first_name,
        "last_name": driver.last_name,
        "team_name": driver.team_name,
        "team_colour": driver.team_colour,
        "headshot_url": driver.headshot_url,
        "country_code": driver.country_code,
    }


def _entry_team_dict(team: EntryTeam) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "team_name": team.team_name,
        "team_colour": team.team_colour,
    }
    if team.livery_image_url is not None:
        payload["livery_image_url"] = team.livery_image_url
    return payload


def _upgrade_dict(raw: Any) -> dict[str, Any]:
    body = _object(raw, "upgrade")
    upgrade_id = str(body.get("upgrade_id") or "")
    if not upgrade_id:
        raise ValueError("upgrade_id is required")
    return {
        "upgrade_id": upgrade_id,
        "pace_delta_sec": _as_float(body.get("pace_delta_sec", 0.0), "pace_delta_sec"),
        "note": str(body.get("note") or ""),
    }


def _compound_from_dict(raw: Any) -> CompoundSpec:
    body = _object(raw, "compound")
    return CompoundSpec(
        compound_id=str(body.get("id", "")).upper(),
        label=str(body.get("label") or body.get("id") or ""),
        dry=_as_bool(body.get("dry", True), "dry"),
        colour=str(body.get("colour") or ""),
        max_laps=_optional_int(body.get("max_laps"), "max_laps"),
        pace_delta_sec=_as_float(body.get("pace_delta_sec", 0.0), "pace_delta_sec"),
        deg_sec_per_lap=_as_float(body.get("deg_sec_per_lap", 0.0), "deg_sec_per_lap"),
    )


def _car_from_dict(raw: Any) -> CarSpec:
    body = _object(raw, "car")
    upgrades = tuple(
        UpgradeSpec(
            upgrade_id=str(item["upgrade_id"]),
            pace_delta_sec=float(item["pace_delta_sec"]),
            note=str(item.get("note") or ""),
        )
        for item in body.get("upgrades", [])
    )
    return CarSpec(
        car_id=str(body.get("car_id") or ""),
        team_name=str(body.get("team_name") or ""),
        team_colour=body.get("team_colour"),
        livery_image_url=body.get("livery_image_url"),
        pace_delta_sec=float(body.get("pace_delta_sec") or 0.0),
        fuel_capacity_kg=body.get("fuel_capacity_kg"),
        fuel_consumption_kg_per_lap=body.get("fuel_consumption_kg_per_lap"),
        starting_fuel_kg=body.get("starting_fuel_kg"),
        upgrades=upgrades,
    )


def _driver_from_dict(raw: Any) -> DriverSpec:
    body = _object(raw, "driver")
    return DriverSpec(
        code=str(body.get("code") or "").upper(),
        driver_number=body.get("driver_number"),
        full_name=str(body.get("full_name") or ""),
        first_name=str(body.get("first_name") or ""),
        last_name=str(body.get("last_name") or ""),
        team_name=str(body.get("team_name") or ""),
        team_colour=body.get("team_colour"),
        headshot_url=body.get("headshot_url"),
        country_code=body.get("country_code"),
        pace_delta_sec=float(body.get("pace_delta_sec") or 0.0),
        car_id=body.get("car_id"),
    )


def _team_from_dict(raw: Any) -> TeamSpec:
    body = _object(raw, "team")
    return TeamSpec(
        team_name=str(body.get("team_name") or ""),
        team_colour=body.get("team_colour"),
        livery_image_url=body.get("livery_image_url"),
    )


def _car_dict(car: CarSpec) -> dict[str, Any]:
    return {
        "car_id": car.car_id,
        "team_name": car.team_name,
        "team_colour": car.team_colour,
        "livery_image_url": car.livery_image_url,
        "pace_delta_sec": car.pace_delta_sec,
        "fuel_capacity_kg": car.fuel_capacity_kg,
        "fuel_consumption_kg_per_lap": car.fuel_consumption_kg_per_lap,
        "starting_fuel_kg": car.starting_fuel_kg,
        "upgrades": [
            {
                "upgrade_id": upgrade.upgrade_id,
                "pace_delta_sec": upgrade.pace_delta_sec,
                "note": upgrade.note,
            }
            for upgrade in car.upgrades
        ],
    }


def _driver_dict(driver: DriverSpec) -> dict[str, Any]:
    return {
        "code": driver.code,
        "driver_number": driver.driver_number,
        "full_name": driver.full_name,
        "first_name": driver.first_name,
        "last_name": driver.last_name,
        "team_name": driver.team_name,
        "team_colour": driver.team_colour,
        "headshot_url": driver.headshot_url,
        "country_code": driver.country_code,
        "pace_delta_sec": driver.pace_delta_sec,
        "car_id": driver.car_id,
    }
