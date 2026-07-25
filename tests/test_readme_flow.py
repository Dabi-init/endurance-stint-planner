"""Verify that documented setup and default-user paths remain reproducible."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "venv",
    "*.egg-info",
    "*.pyc",
)


def _copy_fresh_project(destination: Path) -> None:
    shutil.copytree(ROOT, destination, ignore=COPY_IGNORE)


class TestReadmeQuickStart:
    def test_runtime_dependencies_are_small_and_bounded(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "typer>=" in pyproject and "<1" in pyproject
        assert "rich>=" in pyproject and "<16" in pyproject
        assert "streamlit" not in pyproject
        assert "pandas" not in pyproject

    def test_readme_has_nontechnical_and_powershell_paths(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "Double-click `run.bat`" in readme
        assert (
            "git clone https://github.com/Dabi-init/endurance-stint-planner.git"
            in readme
        )
        assert "run.ps1" in readme
        assert "Python 3.11" in readme
        assert "Evidence Level C" in readme
        assert "Ollama" in readme

    def test_launch_scripts_use_an_isolated_install(self) -> None:
        batch = (ROOT / "run.bat").read_text(encoding="utf-8")
        powershell = (ROOT / "run.ps1").read_text(encoding="utf-8")
        assert "run.ps1" in batch
        assert "python -m venv .venv" in powershell
        assert "-m pip install -e ." in powershell
        assert "-m pitwall doctor" in powershell
        assert "-m pitwall" in powershell

    def test_fresh_clone_core_smoke(self, tmp_path: Path) -> None:
        destination = tmp_path / "fresh-clone"
        _copy_fresh_project(destination)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_strategy_lab.py",
                "-q",
            ],
            capture_output=True,
            text=True,
            cwd=destination,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_documented_product_files_exist(self) -> None:
        for relative_path in [
            "pitwall/cli.py",
            "pitwall/agent.py",
            "requirements.txt",
            "run.bat",
            "run.ps1",
            "examples/README.md",
            "docs/ARCHITECTURE.md",
            "docs/AGENT_BRAIN.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
        ]:
            assert (ROOT / relative_path).exists()

    def test_default_plan_is_feasible(self) -> None:
        from engine.planner import DEFAULT_PRESET, compute_plan, load_preset

        plan = compute_plan(load_preset(DEFAULT_PRESET))
        assert plan.is_feasible, [issue.message for issue in plan.infeasibilities]
