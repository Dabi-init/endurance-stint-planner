"""Versioned, read-only guidance for the optional local Ollama model layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CATALOG_REVIEWED = "2026-08-02"


@dataclass(frozen=True)
class ModelOption:
    """One explicit storage and operating-mode choice shown to the user."""

    key: str
    label: str
    model: str | None
    approximate_model_gb: float
    purpose: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        pull_command = f"ollama pull {self.model}" if self.model else None
        select_command = (
            f"pitwall model use {self.model}" if self.model else "pitwall model off"
        )
        return {
            "choice": self.key,
            "label": self.label,
            "model": self.model,
            "approximate_model_package_gb": self.approximate_model_gb,
            "purpose": self.purpose,
            "status": self.status,
            "pull_command": pull_command,
            "select_command": select_command,
        }


CORE_ONLY = ModelOption(
    key="core-only",
    label="Core only",
    model=None,
    approximate_model_gb=0.0,
    purpose="Every deterministic feature, with no model storage or AI runtime.",
    status="verified-operational-path",
)
SMALLER_CANDIDATE = ModelOption(
    key="smaller-candidate",
    label="Smaller candidate",
    model="qwen3:4b",
    approximate_model_gb=2.5,
    purpose="A smaller package to evaluate when the 8B download is too large.",
    status="unverified-candidate",
)
FIRST_TRY = ModelOption(
    key="first-try",
    label="Provisional first try",
    model="qwen3:8b",
    approximate_model_gb=5.2,
    purpose="The first optional model Pitwall suggests evaluating for routing.",
    status="unverified-candidate",
)

MODEL_OPTIONS = (CORE_ONLY, FIRST_TRY, SMALLER_CANDIDATE)
