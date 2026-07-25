"""Friendly terminal interface for Pitwall Agent."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from engine.models import Driver, DriverCategory, RaceConfig
from engine.planner import DEFAULT_PRESET, list_presets, load_preset, validate_config
from engine.strategy import compare_strategies
from pitwall import __version__
from pitwall.agent import AgentReply, PitwallAgent
from pitwall.providers import ProviderError, list_local_models
from pitwall.tools import CURRENT_RACE, ToolResult, build_registry
from pitwall.workspace import PitwallWorkspace, WorkspaceError

app = typer.Typer(
    name="pitwall",
    help="Local-first endurance race strategy agent.",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
)
model_app = typer.Typer(help="Configure the optional local Ollama model.")
race_app = typer.Typer(help="Create and edit the current race configuration.")
app.add_typer(model_app, name="model")
app.add_typer(race_app, name="race")
console = Console()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


class State:
    def __init__(self, home: Path | None, json_output: bool) -> None:
        self.workspace = PitwallWorkspace.from_path(home)
        self.json_output = json_output


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    home: Annotated[
        Path | None,
        typer.Option(
            "--home",
            help="Pitwall workspace. Default: ./.pitwall",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the installed version."),
    ] = False,
) -> None:
    """Run a command, or open the interactive pit wall when no command is given."""
    if version:
        console.print(f"Pitwall Agent {__version__}")
        raise typer.Exit()
    state = State(home, json_output)
    ctx.obj = state
    if ctx.invoked_subcommand is None:
        if sys.stdin.isatty():
            _interactive(state)
        else:
            console.print(ctx.get_help())


@app.command()
def init(ctx: typer.Context) -> None:
    """Create a local Pitwall race workspace."""
    state: State = ctx.obj
    created = state.workspace.initialise()
    payload = {
        "created": created,
        "workspace": str(state.workspace.root),
        "model": "off",
    }
    _emit(
        state,
        payload,
        (
            f"[green]Ready:[/green] {state.workspace.root}\n"
            "The deterministic race tools work now. Ollama remains optional."
        ),
    )


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check the strategy core, workspace, and optional Ollama connection."""
    state: State = ctx.obj
    state.workspace.initialise()
    settings = state.workspace.settings()
    checks: list[dict[str, Any]] = []

    try:
        plan = compare_strategies(load_preset(DEFAULT_PRESET), iterations=20)
        checks.append(
            {
                "check": "strategy core",
                "status": "pass" if plan.preferred.plan.is_feasible else "fail",
                "detail": (
                    f"{plan.preferred.name}, {plan.preferred.plan.predicted_laps} laps"
                ),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        checks.append({"check": "strategy core", "status": "fail", "detail": str(exc)})

    checks.append(
        {
            "check": "workspace",
            "status": "pass",
            "detail": str(state.workspace.root),
        }
    )
    settings_issues = settings.validate()
    checks.append(
        {
            "check": "configuration",
            "status": "pass" if not settings_issues else "fail",
            "detail": "; ".join(settings_issues) or "valid",
        }
    )

    try:
        models = list_local_models(settings)
        selected = (
            f"selected: {settings.model}"
            if settings.model
            else "no model selected (optional)"
        )
        checks.append(
            {
                "check": "Ollama",
                "status": "pass",
                "detail": f"{len(models)} local model(s); {selected}",
            }
        )
    except ProviderError:
        checks.append(
            {
                "check": "Ollama",
                "status": "optional",
                "detail": "not running; deterministic mode is available",
            }
        )

    payload = {
        "version": __version__,
        "python": platform.python_version(),
        "checks": checks,
        "ready": all(item["status"] != "fail" for item in checks),
    }
    if state.json_output:
        _print_json(payload)
        return
    table = Table(title="Pitwall doctor", show_header=True)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for item in checks:
        colour = {"pass": "green", "fail": "red", "optional": "yellow"}[item["status"]]
        table.add_row(
            item["check"], f"[{colour}]{item['status']}[/{colour}]", item["detail"]
        )
    console.print(table)


@app.command()
def ingest(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="Telemetry CSV to import.")],
    name: Annotated[
        str | None,
        typer.Option("--name", help="Optional safe name inside the workspace."),
    ] = None,
) -> None:
    """Copy telemetry into the workspace and immediately audit its quality."""
    state: State = ctx.obj
    try:
        target = state.workspace.ingest(file, name=name)
        result = build_registry(state.workspace).execute(
            "inspect_telemetry", {"file": target.name}
        )
    except WorkspaceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {"imported": str(target), **result.to_dict()}
    quality = result.data.get("quality", {})
    _emit(
        state,
        payload,
        (
            f"[green]Imported[/green] {target.name}\n"
            f"Quality {quality.get('score', '?')}/100 · "
            f"{quality.get('confidence', '?')} confidence · "
            f"evidence {quality.get('evidence_level', '?')}"
        ),
    )


@app.command()
def plan(
    ctx: typer.Context,
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Race preset name."),
    ] = CURRENT_RACE,
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Conservative, Balanced, or Fuel Save."),
    ] = "Balanced",
) -> None:
    """Calculate a deterministic stint plan."""
    state: State = ctx.obj
    state.workspace.initialise()
    result = build_registry(state.workspace).execute(
        "plan_race",
        {"preset": preset, "strategy": strategy},
    )
    _print_plan_result(state, result)


@app.command()
def compare(
    ctx: typer.Context,
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Race preset name."),
    ] = CURRENT_RACE,
) -> None:
    """Rank three explainable strategies under the same uncertainty."""
    state: State = ctx.obj
    state.workspace.initialise()
    result = build_registry(state.workspace).execute(
        "compare_race_strategies", {"preset": preset}
    )
    _print_comparison(state, result)


@app.command()
def scenario(
    ctx: typer.Context,
    deploy_min: Annotated[float, typer.Argument(help="SC deployment, race minutes.")],
    duration_min: Annotated[float, typer.Argument(help="SC duration in minutes.")],
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Race preset name."),
    ] = CURRENT_RACE,
) -> None:
    """Run a declared pre-race Safety Car what-if."""
    state: State = ctx.obj
    state.workspace.initialise()
    result = build_registry(state.workspace).execute(
        "simulate_safety_car",
        {
            "deploy_min": deploy_min,
            "duration_min": duration_min,
            "preset": preset,
        },
    )
    if state.json_output:
        _print_json(result.to_dict())
        return
    _require_ok(result)
    console.print(
        Panel.fit(
            (
                f"Baseline: [bold]{result.data['baseline_laps']} laps[/bold]\n"
                f"Scenario: [bold]{result.data['scenario_laps']} laps[/bold]\n"
                f"Fuel change: [bold]{result.data['fuel_saved_liters']} L[/bold]\n"
                f"Confidence: {result.data['confidence']}"
            ),
            title="Safety Car scenario — not live race control",
        )
    )
    for note in result.data["notes"]:
        console.print(f"  • {note}")


@app.command()
def ask(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Plain-language race question.")],
) -> None:
    """Ask the bounded agent; it uses Ollama when configured."""
    state: State = ctx.obj
    reply = PitwallAgent(state.workspace).ask(question)
    _print_agent_reply(state, reply)


@app.command()
def export(
    ctx: typer.Context,
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="New report file name."),
    ] = "pit-sheet",
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Race preset name."),
    ] = CURRENT_RACE,
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Strategy to export."),
    ] = "Balanced",
) -> None:
    """Create a new Markdown pit sheet; never overwrite an existing report."""
    state: State = ctx.obj
    result = build_registry(state.workspace).execute(
        "export_pit_sheet",
        {"name": name, "preset": preset, "strategy": strategy},
    )
    _emit(
        state,
        result.to_dict(),
        (
            f"[green]Created[/green] {result.data.get('created', result.error)}"
            if result.ok
            else f"[red]Not created:[/red] {result.error}"
        ),
    )


@app.command()
def tools(ctx: typer.Context) -> None:
    """List the allowlisted functions available to the local model."""
    state: State = ctx.obj
    registry = build_registry(state.workspace)
    if state.json_output:
        _print_json({"tools": registry.schemas()})
        return
    table = Table(title="Audited race tools")
    table.add_column("Tool")
    table.add_column("Purpose")
    for schema in registry.schemas():
        function = schema["function"]
        table.add_row(function["name"], function["description"])
    console.print(table)


@app.command()
def history(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
) -> None:
    """Show recent local agent turns."""
    state: State = ctx.obj
    agent = PitwallAgent(state.workspace)
    entries = agent.history.recent(limit=limit)
    if state.json_output:
        _print_json({"history": entries})
        return
    if not entries:
        console.print("No local session history yet.")
        return
    for entry in entries:
        tools_used = ", ".join(entry.get("used_tools", []))
        suffix = f" [{tools_used}]" if tools_used else ""
        console.print(
            f"[dim]{entry.get('timestamp', '')}[/dim] "
            f"[bold]{entry.get('role', '?')}[/bold]{suffix}: "
            f"{entry.get('content', '')}"
        )


@race_app.command("init")
def race_init(
    ctx: typer.Context,
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Bundled preset to start from."),
    ] = DEFAULT_PRESET,
    replace_existing: Annotated[
        bool,
        typer.Option(
            "--replace",
            help="Explicitly replace the existing current race.",
        ),
    ] = False,
) -> None:
    """Create an editable race.json from a known-good bundled preset."""
    state: State = ctx.obj
    if preset not in list_presets():
        raise typer.BadParameter(
            f"Unknown preset. Choose from: {', '.join(list_presets())}"
        )
    config = load_preset(preset)
    try:
        path = state.workspace.save_race(
            config.to_dict(),
            overwrite=replace_existing,
        )
    except WorkspaceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        state,
        {"created": str(path), "race": config.to_dict()},
        (
            f"[green]Current race created:[/green] {config.race_name}\n"
            "Use `pitwall race set --help` to enter your car and event values."
        ),
    )


@race_app.command("set")
def race_set(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Event or race name."),
    ] = None,
    duration: Annotated[
        float | None,
        typer.Option("--duration", help="Scheduled duration in hours.", min=0.01),
    ] = None,
    lap_time: Annotated[
        float | None,
        typer.Option("--lap-time", help="Representative green lap in seconds.", min=1),
    ] = None,
    tank: Annotated[
        float | None,
        typer.Option("--tank", help="Usable fuel tank in litres.", min=0.1),
    ] = None,
    burn: Annotated[
        float | None,
        typer.Option("--burn", help="Fuel consumption in litres per lap.", min=0.001),
    ] = None,
    pit_loss: Annotated[
        float | None,
        typer.Option("--pit-loss", help="Pit-lane transit loss in seconds.", min=0),
    ] = None,
    refuel_rate: Annotated[
        float | None,
        typer.Option(
            "--refuel-rate",
            help="Refuelling speed in litres/second.",
            min=0.01,
        ),
    ] = None,
    tyre_life: Annotated[
        int | None,
        typer.Option("--tyre-life", help="Intended tyre life in laps.", min=1),
    ] = None,
    tyre_change_time: Annotated[
        float | None,
        typer.Option("--tyre-change-time", help="Tyre service seconds.", min=0),
    ] = None,
    driver_change_time: Annotated[
        float | None,
        typer.Option("--driver-change-time", help="Driver change seconds.", min=0),
    ] = None,
    service_mode: Annotated[
        str | None,
        typer.Option("--service-mode", help="parallel or sequential pit work."),
    ] = None,
    drivers: Annotated[
        str | None,
        typer.Option(
            "--drivers",
            help='Comma list: "Alex:Pro:0, Sam:Silver:0.5, Lee:Bronze:1.2".',
        ),
    ] = None,
    reserve_laps: Annotated[
        int | None,
        typer.Option("--reserve-laps", help="Fuel reserve in whole laps.", min=0),
    ] = None,
    pro_max_stint: Annotated[
        float | None,
        typer.Option("--pro-max-stint", help="Pro continuous minutes.", min=1),
    ] = None,
    silver_max_stint: Annotated[
        float | None,
        typer.Option("--silver-max-stint", help="Silver continuous minutes.", min=1),
    ] = None,
    bronze_max_stint: Annotated[
        float | None,
        typer.Option("--bronze-max-stint", help="Bronze continuous minutes.", min=1),
    ] = None,
    silver_min_drive: Annotated[
        float | None,
        typer.Option("--silver-min-drive", help="Silver minimum total minutes.", min=0),
    ] = None,
    bronze_min_drive: Annotated[
        float | None,
        typer.Option("--bronze-min-drive", help="Bronze minimum total minutes.", min=0),
    ] = None,
    driver_max_total: Annotated[
        float | None,
        typer.Option(
            "--driver-max-total",
            help="Maximum total minutes per driver; zero disables.",
            min=0,
        ),
    ] = None,
) -> None:
    """Update only the supplied current-race values."""
    state: State = ctx.obj
    try:
        config = RaceConfig.from_dict(state.workspace.race_data())
    except WorkspaceError as exc:
        raise typer.BadParameter(str(exc)) from exc

    updates = {
        "race_name": name,
        "race_duration_hours": duration,
        "base_lap_time_sec": lap_time,
        "fuel_tank_liters": tank,
        "fuel_consumption_per_lap": burn,
        "pit_stop_time_loss_sec": pit_loss,
        "refuel_rate_liters_per_sec": refuel_rate,
        "tyre_life_laps": tyre_life,
        "tyre_change_time_sec": tyre_change_time,
        "driver_change_time_sec": driver_change_time,
    }
    for attribute, value in updates.items():
        if value is not None:
            setattr(config, attribute, value)

    if service_mode is not None:
        normalised_mode = service_mode.strip().lower()
        if normalised_mode not in {"parallel", "sequential"}:
            raise typer.BadParameter("--service-mode must be parallel or sequential")
        config.services_parallel = normalised_mode == "parallel"
    if drivers is not None:
        try:
            config.drivers = _parse_drivers(drivers)
            config.ensure_unique_driver_ids()
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    regulation_updates = {
        "fuel_safety_laps": reserve_laps,
        "pro_max_continuous_stint_min": pro_max_stint,
        "silver_max_continuous_stint_min": silver_max_stint,
        "bronze_max_continuous_stint_min": bronze_max_stint,
        "silver_min_drive_min": silver_min_drive,
        "bronze_min_drive_min": bronze_min_drive,
        "max_total_drive_min": driver_max_total,
    }
    for attribute, value in regulation_updates.items():
        if value is not None:
            setattr(config.regulations, attribute, value)

    state.workspace.save_race(config.to_dict(), overwrite=True)
    issues = validate_config(config)
    payload = {
        "updated": str(state.workspace.race_path),
        "race": config.to_dict(),
        "validation": [issue.to_dict() for issue in issues],
    }
    message = f"[green]Updated current race:[/green] {config.race_name}"
    if issues:
        message += (
            f"\n[yellow]{len(issues)} planning issue(s); run `pitwall plan`.[/yellow]"
        )
    _emit(state, payload, message)


@race_app.command("show")
def race_show(ctx: typer.Context) -> None:
    """Show the exact current-race inputs used by the strategy tools."""
    state: State = ctx.obj
    try:
        config = RaceConfig.from_dict(state.workspace.race_data())
    except WorkspaceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = config.to_dict()
    if state.json_output:
        _print_json(payload)
        return
    table = Table(title=config.race_name)
    table.add_column("Input")
    table.add_column("Value")
    rows = [
        ("Duration", f"{config.race_duration_hours:g} h"),
        ("Green lap", f"{config.base_lap_time_sec:g} s"),
        ("Usable tank", f"{config.fuel_tank_liters:g} L"),
        ("Fuel burn", f"{config.fuel_consumption_per_lap:g} L/lap"),
        ("Pit transit", f"{config.pit_stop_time_loss_sec:g} s"),
        ("Refuel rate", f"{config.refuel_rate_liters_per_sec:g} L/s"),
        ("Tyre life", f"{config.tyre_life_laps} laps"),
        ("Service", "parallel" if config.services_parallel else "sequential"),
        (
            "Drivers",
            ", ".join(
                f"{driver.name} ({driver.category.value})" for driver in config.drivers
            ),
        ),
    ]
    for label, value in rows:
        table.add_row(label, value)
    console.print(table)


@model_app.command("list")
def model_list(ctx: typer.Context) -> None:
    """List models already installed in local Ollama."""
    state: State = ctx.obj
    state.workspace.initialise()
    try:
        models = list_local_models(state.workspace.settings())
    except ProviderError as exc:
        console.print(f"[yellow]Ollama is not reachable:[/yellow] {exc}")
        raise typer.Exit(code=1) from exc
    if state.json_output:
        _print_json({"models": models})
        return
    if not models:
        console.print("Ollama is running, but no models are installed.")
        return
    console.print("\n".join(f"  • {name}" for name in models))


@model_app.command("use")
def model_use(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="An Ollama model already installed.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Save even when Ollama cannot verify the model."),
    ] = False,
) -> None:
    """Select a local Ollama model without changing application code."""
    state: State = ctx.obj
    state.workspace.initialise()
    settings = state.workspace.settings()
    if not force:
        try:
            models = list_local_models(settings)
        except ProviderError as exc:
            raise typer.BadParameter(
                "Ollama is not running. Start it, or use --force."
            ) from exc
        if name not in models:
            raise typer.BadParameter(
                f"{name!r} is not installed. Available: {', '.join(models) or 'none'}"
            )
    updated = replace(settings, provider="ollama", model=name)
    state.workspace.save_settings(updated)
    _emit(
        state,
        {"provider": "ollama", "model": name},
        f"[green]Selected local model:[/green] {name}",
    )


@model_app.command("off")
def model_off(ctx: typer.Context) -> None:
    """Disable the model layer; deterministic commands remain available."""
    state: State = ctx.obj
    state.workspace.initialise()
    settings = state.workspace.settings()
    state.workspace.save_settings(replace(settings, provider="none", model=""))
    _emit(
        state,
        {"provider": "none", "model": ""},
        "Model layer is off. Deterministic mode remains ready.",
    )


def _interactive(state: State) -> None:
    state.workspace.initialise()
    console.print(
        Panel.fit(
            "[bold red]PITWALL AGENT[/bold red]\n"
            "Deterministic race tools · optional local Ollama · no cloud telemetry\n"
            "[dim]Ask a question, or type exit.[/dim]",
            border_style="red",
        )
    )
    session_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    agent = PitwallAgent(state.workspace)
    while True:
        try:
            question = Prompt.ask("[bold cyan]pitwall[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nSession closed.")
            return
        if question.lower() in {"exit", "quit", "/exit", "/quit"}:
            console.print("Session closed.")
            return
        _print_agent_reply(state, agent.ask(question, session_id=session_id))


def _print_agent_reply(state: State, reply: AgentReply) -> None:
    if state.json_output:
        _print_json(
            {
                "answer": reply.answer,
                "mode": reply.mode,
                "used_tools": list(reply.used_tools),
                "warnings": list(reply.warnings),
            }
        )
        return
    console.print(Markdown(reply.answer))
    mode = f"mode: {reply.mode}"
    if reply.used_tools:
        mode += " · tools: " + ", ".join(reply.used_tools)
    console.print(f"[dim]{mode}[/dim]")
    for warning in reply.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _print_plan_result(state: State, result: ToolResult) -> None:
    if state.json_output:
        _print_json(result.to_dict())
        return
    _require_ok(result)
    plan = result.data["plan"]
    console.print(
        Panel.fit(
            (
                f"[bold]{result.data['strategy']}[/bold] · "
                f"{plan['predicted_laps']} laps · {plan['pit_stops']} stops · "
                f"{plan['fuel_used_liters']} L\n"
                f"Evidence {result.data['evidence']['evidence_level']} · "
                f"{result.data['evidence']['confidence']} confidence"
            ),
            title=result.data["preset"],
        )
    )
    columns = ("Stint", "Driver", "Start", "End", "Laps", "Fuel start (L)", "Tyre set")
    table = Table(show_header=True)
    for column in columns:
        table.add_column(column)
    for stint in plan["stints"]:
        table.add_row(*(str(stint[column]) for column in columns))
    console.print(table)


def _print_comparison(state: State, result: ToolResult) -> None:
    if state.json_output:
        _print_json(result.to_dict())
        return
    _require_ok(result)
    console.print(
        f"\nRecommendation: [bold green]{result.data['recommendation']}[/bold green]"
    )
    table = Table(title=result.data["preset"])
    columns = [
        "Rank",
        "Strategy",
        "Projected laps",
        "P10 laps",
        "Pit stops",
        "Reserve laps",
        "Extra-stop risk",
        "Risk",
    ]
    for column in columns:
        table.add_column(column)
    for row in result.data["strategies"]:
        table.add_row(*(str(row[column]) for column in columns))
    console.print(table)
    evidence = result.data["evidence"]
    console.print(
        f"[dim]Evidence {evidence['evidence_level']} · "
        f"{evidence['confidence']} confidence · {evidence['source']}[/dim]"
    )


def _emit(state: State, payload: dict[str, Any], text: str) -> None:
    if state.json_output:
        _print_json(payload)
    else:
        console.print(text)


def _require_ok(result: ToolResult) -> None:
    if not result.ok:
        console.print(f"[red]Could not complete the command:[/red] {result.error}")
        raise typer.Exit(code=1)


def _print_json(payload: dict[str, Any]) -> None:
    """Keep machine output valid even in legacy Windows PowerShell code pages."""
    typer.echo(json.dumps(payload, ensure_ascii=True, indent=2))


def _parse_drivers(value: str) -> list[Driver]:
    drivers: list[Driver] = []
    categories = {item.value.lower(): item for item in DriverCategory}
    for index, raw_driver in enumerate(value.split(","), start=1):
        fields = [field.strip() for field in raw_driver.split(":")]
        if len(fields) not in {2, 3} or not fields[0]:
            raise ValueError(
                f"Driver {index} must be Name:Category or Name:Category:PaceDelta"
            )
        category = categories.get(fields[1].lower())
        if category is None:
            raise ValueError("Driver category must be Pro, Silver, or Bronze")
        try:
            pace_delta = float(fields[2]) if len(fields) == 3 else 0.0
        except ValueError as exc:
            raise ValueError(f"Driver {index} pace delta must be a number") from exc
        drivers.append(Driver(fields[0], category, pace_delta))
    if not drivers:
        raise ValueError("At least one driver is required")
    return drivers


if __name__ == "__main__":
    app()
