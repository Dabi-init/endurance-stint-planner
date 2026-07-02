"""Verify README Quick Start paths work (new clone + returning user)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


_COPY_IGNORE = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".pytest_cache",
    "mcps",
    "terminals",
    ".venv",
    "venv",
    "endurance-stint-planner",
    "*.pyc",
)


def _copy_fresh_project(dest: Path) -> None:
    """Copy only what a git clone contains — skip local duplicates and caches."""
    shutil.copytree(ROOT, dest, ignore=_COPY_IGNORE)


class TestReadmeQuickStart:
    def test_requirements_installable(self):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "-q"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        assert result.returncode == 0, result.stderr

    def test_streamlit_and_app_importable(self):
        import streamlit
        import app

        assert streamlit.__version__
        assert app.APP_VERSION

    def test_readme_documents_both_user_paths(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "git clone https://github.com/Dabi-init/endurance-stint-planner.git" in readme
        assert "Already downloaded" in readme or "returning users" in readme.lower()
        assert "run.bat" in readme
        assert "streamlit run app.py" in readme
        assert "Python 3.10" in readme

    def test_returning_user_section_has_no_git_clone_command(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        returning = readme.split("Already downloaded", 1)[-1].split("---", 1)[0]
        code_blocks = re.findall(r"```(?:bash)?\s*\n(.*?)```", returning, re.DOTALL)
        assert code_blocks, "Returning-user section should include a bash code block"
        for block in code_blocks:
            assert "git clone" not in block

    def test_run_bat_exists_and_uses_python_modules(self):
        bat = ROOT / "run.bat"
        assert bat.exists()
        content = bat.read_text(encoding="utf-8")
        assert "python -m pip install" in content
        assert "python -m streamlit run app.py" in content

    def test_fresh_clone_simulation_smoke(self, tmp_path):
        """Simulate new user: copy project to empty dir and verify plan loads."""
        dest = tmp_path / "fresh-clone"
        _copy_fresh_project(dest)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q"],
            capture_output=True,
            text=True,
            cwd=dest,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_returning_user_launch_commands_exist(self):
        assert (ROOT / "app.py").exists()
        assert (ROOT / "requirements.txt").exists()
        assert (ROOT / "presets" / "6h_endurance.json").exists()

    def test_default_plan_feasible_via_readme_commands(self):
        """Exact engine path a new user sees on first page load."""
        from engine.circuits import DEFAULT_CIRCUIT_ID, apply_circuit_to_config, get_circuit
        from engine.models import RaceConfig
        from engine.planner import DEFAULT_PRESET, compute_plan, load_preset

        cfg = apply_circuit_to_config(
            load_preset(DEFAULT_PRESET).to_dict(),
            get_circuit(DEFAULT_CIRCUIT_ID),
        )
        plan = compute_plan(RaceConfig.from_dict(cfg))
        assert plan.is_feasible, [i.message for i in plan.infeasibilities]

    def test_streamlit_cli_available(self):
        result = subprocess.run(
            [sys.executable, "-m", "streamlit", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert re.search(r"\d+\.\d+", result.stdout + result.stderr)