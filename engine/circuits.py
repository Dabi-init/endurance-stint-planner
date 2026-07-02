"""Circuit / track data and track-specific strategy adjustments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CIRCUITS_DIR = Path(__file__).resolve().parent.parent / "circuits"
CIRCUITS_FILE = CIRCUITS_DIR / "circuits.json"

TYRE_WEAR_MULTIPLIERS = {
    "Low": 1.12,
    "Medium": 1.0,
    "High": 0.82,
}

DEG_PER_LAP_BY_WEAR = {
    "Low": 0.04,
    "Medium": 0.07,
    "High": 0.11,
}


@dataclass
class Circuit:
    id: str
    name: str
    country: str
    length_km: float
    base_lap_time_sec: float
    tyre_wear: str
    tyre_life_laps: int
    fuel_consumption_per_lap: float
    pit_loss_sec: float
    sc_risk: str
    characteristics: str = ""

    @property
    def tyre_wear_multiplier(self) -> float:
        return TYRE_WEAR_MULTIPLIERS.get(self.tyre_wear, 1.0)

    @property
    def deg_per_lap_sec(self) -> float:
        return DEG_PER_LAP_BY_WEAR.get(self.tyre_wear, 0.07)

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.country})"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "length_km": self.length_km,
            "base_lap_time_sec": self.base_lap_time_sec,
            "tyre_wear": self.tyre_wear,
            "tyre_life_laps": self.tyre_life_laps,
            "fuel_consumption_per_lap": self.fuel_consumption_per_lap,
            "pit_loss_sec": self.pit_loss_sec,
            "sc_risk": self.sc_risk,
            "characteristics": self.characteristics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Circuit:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            country=str(data.get("country", "")),
            length_km=float(data.get("length_km", 5.0)),
            base_lap_time_sec=float(data.get("base_lap_time_sec", 120.0)),
            tyre_wear=str(data.get("tyre_wear", "Medium")),
            tyre_life_laps=int(data.get("tyre_life_laps", 28)),
            fuel_consumption_per_lap=float(data.get("fuel_consumption_per_lap", 2.9)),
            pit_loss_sec=float(data.get("pit_loss_sec", 50.0)),
            sc_risk=str(data.get("sc_risk", "Medium")),
            characteristics=str(data.get("characteristics", "")),
        )


DEFAULT_CIRCUIT_ID = "spa-francorchamps"


def load_circuits() -> list[Circuit]:
    if not CIRCUITS_FILE.exists():
        return []
    with CIRCUITS_FILE.open(encoding="utf-8") as fh:
        return [Circuit.from_dict(item) for item in json.load(fh)]


def list_circuit_names() -> list[str]:
    return [c.display_name for c in load_circuits()]


def get_circuit(circuit_id: Optional[str] = None) -> Optional[Circuit]:
    circuits = {c.id: c for c in load_circuits()}
    if circuit_id and circuit_id in circuits:
        return circuits[circuit_id]
    return circuits.get(DEFAULT_CIRCUIT_ID) or (load_circuits()[0] if load_circuits() else None)


def circuit_id_from_display(display_name: str) -> Optional[str]:
    for circuit in load_circuits():
        if circuit.display_name == display_name:
            return circuit.id
    return None


def apply_circuit_to_config(
    config_dict: dict,
    circuit: Circuit,
    *,
    preserve_tank: bool = True,
) -> dict:
    """
    Adjust race parameters for the selected circuit.
    High tyre-wear tracks shorten stint length; fuel and pit loss follow circuit data.
    """
    updated = dict(config_dict)
    wear_mult = circuit.tyre_wear_multiplier
    adjusted_tyre_life = max(int(round(circuit.tyre_life_laps * wear_mult)), 8)

    updated["circuit_id"] = circuit.id
    updated["base_lap_time_sec"] = circuit.base_lap_time_sec
    updated["fuel_consumption_per_lap"] = round(circuit.fuel_consumption_per_lap, 2)
    updated["tyre_life_laps"] = adjusted_tyre_life
    updated["pit_stop_time_loss_sec"] = circuit.pit_loss_sec

    if not preserve_tank:
        updated["fuel_tank_liters"] = config_dict.get("fuel_tank_liters", 100.0)

    race_name = updated.get("race_name", "Race")
    if "—" in race_name:
        base = race_name.split("—")[0].strip()
        updated["race_name"] = f"{base} — {circuit.name}"
    else:
        updated["race_name"] = f"{race_name} — {circuit.name}"

    return updated


def recommended_stint_laps(config_dict: dict, circuit: Circuit) -> dict:
    """Return fuel-limited vs tyre-limited geometry for recommendations."""
    from engine.models import RaceConfig
    from engine.planner import fuel_limited_laps

    cfg = RaceConfig.from_dict(config_dict)
    fuel_laps = fuel_limited_laps(cfg)
    tyre_laps = config_dict.get("tyre_life_laps", circuit.tyre_life_laps)
    return {
        "fuel_laps": fuel_laps,
        "tyre_laps": tyre_laps,
        "recommended_laps": min(fuel_laps, tyre_laps) if fuel_laps and tyre_laps else 0,
        "limiting": (
            "Fuel" if fuel_laps < tyre_laps
            else "Tyre" if tyre_laps < fuel_laps
            else "Equal"
        ),
    }