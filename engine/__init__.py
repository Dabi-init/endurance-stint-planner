"""Endurance race stint planning engine — pure Python, no UI dependencies."""

from engine.models import (
    Driver,
    DriverCategory,
    DriverRegulations,
    Infeasibility,
    PlanResult,
    RaceConfig,
    Stint,
)
from engine.planner import compute_plan, load_preset, list_presets
from engine.regulations import check_compliance
from engine.safety_car import replan_with_safety_car
from engine.circuits import Circuit, apply_circuit_to_config, get_circuit, load_circuits
from engine.recommendations import StrategyReport, generate_strategy_report

__all__ = [
    "Driver",
    "DriverCategory",
    "DriverRegulations",
    "Infeasibility",
    "PlanResult",
    "RaceConfig",
    "Stint",
    "compute_plan",
    "load_preset",
    "list_presets",
    "check_compliance",
    "replan_with_safety_car",
    "Circuit",
    "apply_circuit_to_config",
    "get_circuit",
    "load_circuits",
    "StrategyReport",
    "generate_strategy_report",
]