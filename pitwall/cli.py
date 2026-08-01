"""Friendly terminal interface for Pitwall Agent."""

from __future__ import annotations

import json
import math
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
from rich.prompt import Confirm, Prompt
from rich.table import Table

from engine.models import Driver, DriverCategory, RaceConfig
from engine.planner import DEFAULT_PRESET, list_presets, load_preset, validate_config
from engine.strategy import compare_strategies
from pitwall import __version__
from pitwall.agent import AgentReply, PitwallAgent
from pitwall.config import Settings
from pitwall.guided import (
    GUIDED_FIELDS,
    PRESET_ORIGIN,
    REGULATION_NOTICE,
    GuidedValueError,
    build_race_config,
    cross_check,
    parse_field,
    preset_defaults,
    summary_rows,
)
from pitwall.model_advisor import (
    CATALOG_REVIEWED,
    CORE_ONLY,
    FIRST_TRY,
    MODEL_OPTIONS,
)
from pitwall.providers import ProviderError, list_local_models
from pitwall.tools import (
    CURRENT_RACE,
    PRE_RACE_ONLY_HEADER,
    SAFETY_CAR_DISCLAIMER,
    ToolResult,
    build_registry,
)
from pitwall.validation_report import (
    PROVENANCE_DISCLAIMERS,
    ValidationInputError,
    build_comparison,
    parse_stint_lengths,
    render_report,
    report_filename,
)
from pitwall.welcome import (
    GUIDED_OFFER,
    WELCOME_INTRO,
    WELCOME_NEXT_STEPS,
    WELCOME_SECTIONS,
    WELCOME_TITLE,
    welcome_payload,
)
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
def init(
    ctx: typer.Context,
    guided: Annotated[
        bool,
        typer.Option(
            "--guided",
            help="Answer step-by-step prompts to build race.json with safe ranges.",
        ),
    ] = False,
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Preset used for guided fallbacks."),
    ] = DEFAULT_PRESET,
    replace_existing: Annotated[
        bool,
        typer.Option("--replace", help="Replace an existing current race."),
    ] = False,
) -> None:
    """Create a local Pitwall race workspace, optionally with guided setup."""
    state: State = ctx.obj
    created = state.workspace.initialise()
    if guided:
        _guided_init(state, preset=preset, replace_existing=replace_existing)
        return
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
            "The deterministic race tools work now. Ollama remains optional.\n"
            "New to endurance strategy? Run `pitwall welcome`."
        ),
    )


@app.command()
def welcome(ctx: typer.Context) -> None:
    """Explain the core ideas in plain English before you plan anything."""
    state: State = ctx.obj
    if state.json_output:
        _print_json(welcome_payload())
        return
    _print_welcome_content()
    if not sys.stdin.isatty():
        return
    try:
        wants_setup = Confirm.ask("Start guided setup now?", default=False)
    except (EOFError, KeyboardInterrupt):  # pragma: no cover - interactive only
        console.print("\nNo changes made.")
        return
    if wants_setup:
        state.workspace.initialise()
        _guided_init(state, preset=DEFAULT_PRESET, replace_existing=False)


def _print_welcome_content() -> None:
    console.print(
        Panel.fit(
            f"[bold red]{WELCOME_TITLE}[/bold red]\n{WELCOME_INTRO}", border_style="red"
        )
    )
    for heading, body in WELCOME_SECTIONS:
        console.print(f"\n[bold]{heading}[/bold]")
        console.print(f"  {body}")
    console.print("\n[bold]Next steps[/bold]")
    for step in WELCOME_NEXT_STEPS:
        console.print(f"  {step}")
    console.print(f"\n[dim]{GUIDED_OFFER}[/dim]")


@app.command()
def doctor(
    ctx: typer.Context,
    core_only: Annotated[
        bool,
        typer.Option(
            "--core-only",
            help="Check local planning and workspace readiness without contacting Ollama.",
        ),
    ] = False,
) -> None:
    """Check the strategy core, workspace, and optional Ollama connection."""
    state: State = ctx.obj
    state.workspace.initialise()
    checks: list[dict[str, Any]] = []

    settings: Settings | None
    try:
        settings = state.workspace.settings()
        settings_error = ""
    except (WorkspaceError, ValueError) as exc:
        settings = None
        settings_error = str(exc)

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
    settings_issues = settings.validate() if settings is not None else [settings_error]
    checks.append(
        {
            "check": "configuration",
            "status": "pass" if not settings_issues else "fail",
            "detail": "; ".join(settings_issues) or "valid",
        }
    )

    if settings is None:
        checks.append(
            {
                "check": "Ollama",
                "status": "optional",
                "detail": "not checked until config.toml is repaired",
            }
        )
    elif core_only:
        checks.append(
            {
                "check": "Ollama",
                "status": "optional",
                "detail": "not contacted during the core-only check",
            }
        )
    elif not settings.model_enabled:
        checks.append(
            {
                "check": "Ollama",
                "status": "optional",
                "detail": (
                    "disabled; no local service contacted; run "
                    "'pitwall model recommend' for read-only choices"
                ),
            }
        )
    else:
        try:
            models = list_local_models(settings)
            if settings.model and settings.model not in models:
                ollama_status = "fail"
                selected = f"selected model is not installed: {settings.model}"
            elif settings.model:
                ollama_status = "pass"
                selected = f"selected: {settings.model}"
            else:
                ollama_status = "optional"
                selected = "no model selected (optional)"
            checks.append(
                {
                    "check": "Ollama",
                    "status": ollama_status,
                    "detail": f"{len(models)} local model(s); {selected}",
                }
            )
        except ProviderError as exc:
            selected_model_required = settings.model_enabled
            checks.append(
                {
                    "check": "Ollama",
                    "status": "fail" if selected_model_required else "optional",
                    "detail": (
                        f"selected model unavailable ({settings.model}): {exc}; "
                        "deterministic mode is still available"
                        if selected_model_required
                        else "not running; deterministic mode is available"
                    ),
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
    else:
        table = Table(title="Pitwall doctor", show_header=True)
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for item in checks:
            colour = {"pass": "green", "fail": "red", "optional": "yellow"}[
                item["status"]
            ]
            table.add_row(
                item["check"],
                f"[{colour}]{item['status']}[/{colour}]",
                item["detail"],
            )
        console.print(table)
    if not payload["ready"]:
        raise typer.Exit(code=1)


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
    previous_state = state.workspace.state()
    try:
        target = state.workspace.ingest(file, name=name)
        result = build_registry(state.workspace).execute(
            "inspect_telemetry", {"file": target.name}
        )
    except WorkspaceError as exc:
        _command_error(state, str(exc))
    payload = {"imported": str(target), **result.to_dict()}
    if not result.ok:
        cleanup_errors: list[str] = []
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_errors.append(f"could not remove {target.name}: {exc}")
        try:
            state.workspace.write_state(previous_state)
        except (OSError, WorkspaceError) as exc:
            cleanup_errors.append(f"could not restore prior selection: {exc}")
        payload["imported"] = None
        payload["cleanup_errors"] = cleanup_errors
        cleanup_note = (
            "\nCleanup warning: " + "; ".join(cleanup_errors)
            if cleanup_errors
            else "\nThe rejected copy was removed and the prior telemetry restored."
        )
        _emit(
            state,
            payload,
            (f"[red]Telemetry import was rejected:[/red] {result.error}{cleanup_note}"),
        )
        raise typer.Exit(code=1)
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
        _print_tool_json(result)
        return
    _require_ok(result)
    console.print(f"[yellow]{SAFETY_CAR_DISCLAIMER}[/yellow]")
    console.print(
        Panel.fit(
            (
                f"Baseline: [bold]{result.data['baseline_laps']} laps[/bold]\n"
                f"Scenario: [bold]{result.data['scenario_laps']} laps[/bold]\n"
                f"Fuel change: [bold]{result.data['fuel_saved_liters']} L[/bold]\n"
                f"Confidence: {result.data['confidence']}\n"
                f"Input source: {result.data['input_source']}"
            ),
            title="Safety Car scenario — not live race control",
        )
    )
    for note in result.data["notes"]:
        console.print(f"  • {note}")
    _print_trigger_cards(result.data)


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
        typer.Option(
            "--strategy",
            "-s",
            help=(
                "Strategy to export. Default: the recommended strategy from "
                "`pitwall compare`. Pass a name to override it."
            ),
        ),
    ] = "",
) -> None:
    """Export the recommended strategy (or --strategy) as a new pit sheet.

    The pit sheet is always written to a new file; existing reports are never
    overwritten.
    """
    state: State = ctx.obj
    result = build_registry(state.workspace).execute(
        "export_pit_sheet",
        {"name": name, "preset": preset, "strategy": strategy},
    )
    if result.ok:
        chosen = result.data.get("strategy", strategy)
        origin = (
            "recommended strategy"
            if result.data.get("recommended")
            else "strategy you requested"
        )
        message = (
            f"[green]Created[/green] {result.data.get('created')}\n"
            f"Exported the {origin}: [bold]{chosen}[/bold] · "
            f"{result.data.get('input_source', '')}"
        )
    else:
        message = f"[red]Not created:[/red] {result.error}"
    _emit(state, result.to_dict(), message)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command()
def validate(
    ctx: typer.Context,
    actual_laps: Annotated[
        int | None,
        typer.Option("--actual-laps", help="Laps you actually completed.", min=0),
    ] = None,
    actual_stops: Annotated[
        int | None,
        typer.Option("--actual-stops", help="Pit stops you actually made.", min=0),
    ] = None,
    actual_fuel_burn: Annotated[
        float | None,
        typer.Option(
            "--actual-fuel-burn",
            help="Measured fuel burn in litres per lap.",
            min=0.0,
        ),
    ] = None,
    actual_stint_lengths: Annotated[
        str | None,
        typer.Option(
            "--actual-stint-lengths",
            help='Comma-separated actual stint laps, e.g. "18,19,17".',
        ),
    ] = None,
    preset: Annotated[
        str,
        typer.Option("--preset", "-p", help="Race preset name."),
    ] = CURRENT_RACE,
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Planned strategy to compare against."),
    ] = "Balanced",
) -> None:
    """Compare a finished race you report against the pre-race plan.

    The actual values are typed in by you, are not independently verified, and
    the report stays at Evidence Level C. This is not a validation claim.
    """
    state: State = ctx.obj
    state.workspace.initialise()
    try:
        stints = parse_stint_lengths(actual_stint_lengths)
    except ValidationInputError as exc:
        _command_error(state, str(exc))
    if (
        actual_laps is None
        and actual_stops is None
        and actual_fuel_burn is None
        and not stints
    ):
        _command_error(
            state,
            "Supply at least one actual result: --actual-laps, --actual-stops, "
            "--actual-fuel-burn, or --actual-stint-lengths.",
        )
    if actual_fuel_burn is not None and not math.isfinite(actual_fuel_burn):
        _command_error(state, "--actual-fuel-burn must be a finite number")
    planned = _planned_reference(state, preset, strategy)
    actual = {
        "laps": None if actual_laps is None else float(actual_laps),
        "stops": None if actual_stops is None else float(actual_stops),
        "fuel_burn_per_lap": actual_fuel_burn,
        "stint_lengths": stints,
    }
    rows = build_comparison(planned, actual)
    generated_at = datetime.now(UTC)
    markdown = render_report(
        planned["race_name"],
        planned["strategy"],
        planned,
        actual,
        rows,
        generated_at=generated_at,
    )
    try:
        target = state.workspace.write_new_validation(
            report_filename(generated_at),
            markdown,
        )
    except WorkspaceError as exc:
        _command_error(state, str(exc))
    payload = {
        "created": str(target),
        "race_name": planned["race_name"],
        "strategy": planned["strategy"],
        "evidence_level": "C",
        "planned": planned,
        "actual": actual,
        "comparison": [row.to_dict() for row in rows],
        "disclaimers": list(PROVENANCE_DISCLAIMERS),
    }
    if state.json_output:
        _print_json(payload)
        return
    table = Table(title=f"Planned versus reported: {planned['race_name']}")
    for column in ("Metric", "Unit", "Planned", "Actual", "Difference", "Deviation"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row.metric,
            row.unit,
            "-" if row.planned is None else f"{row.planned:g}",
            f"{row.actual:g}",
            "-" if row.difference is None else f"{row.difference:+g}",
            "-" if row.deviation_pct is None else f"{row.deviation_pct:+.2f}%",
        )
    console.print(table)
    for disclaimer in PROVENANCE_DISCLAIMERS:
        console.print(f"[yellow]•[/yellow] {disclaimer}")
    console.print(f"[green]Saved[/green] {target}")


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
        _command_error(
            state, f"Unknown preset. Choose from: {', '.join(list_presets())}"
        )
    config = load_preset(preset)
    try:
        path = state.workspace.save_race(
            config.to_dict(),
            overwrite=replace_existing,
        )
    except WorkspaceError as exc:
        _command_error(state, str(exc))
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
        typer.Option(
            "--duration", help="Scheduled duration in hours.", min=0.01, max=48
        ),
    ] = None,
    lap_time: Annotated[
        float | None,
        typer.Option(
            "--lap-time",
            help="Representative green lap in seconds.",
            min=20,
            max=900,
        ),
    ] = None,
    tank: Annotated[
        float | None,
        typer.Option("--tank", help="Usable fuel tank in litres.", min=0.1, max=250),
    ] = None,
    burn: Annotated[
        float | None,
        typer.Option(
            "--burn",
            help="Fuel consumption in litres per lap.",
            min=0.001,
            max=60,
        ),
    ] = None,
    pit_loss: Annotated[
        float | None,
        typer.Option(
            "--pit-loss", help="Pit-lane transit loss in seconds.", min=0, max=3600
        ),
    ] = None,
    refuel_rate: Annotated[
        float | None,
        typer.Option(
            "--refuel-rate",
            help="Refuelling speed in litres/second.",
            min=0.01,
            max=100,
        ),
    ] = None,
    tyre_life: Annotated[
        int | None,
        typer.Option("--tyre-life", help="Intended tyre life in laps.", min=1, max=200),
    ] = None,
    tyre_change_time: Annotated[
        float | None,
        typer.Option(
            "--tyre-change-time", help="Tyre service seconds.", min=0, max=3600
        ),
    ] = None,
    driver_change_time: Annotated[
        float | None,
        typer.Option(
            "--driver-change-time", help="Driver change seconds.", min=0, max=3600
        ),
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
        typer.Option(
            "--reserve-laps", help="Fuel reserve in whole laps.", min=0, max=100
        ),
    ] = None,
    pro_max_stint: Annotated[
        float | None,
        typer.Option(
            "--pro-max-stint", help="Pro continuous minutes.", min=1, max=1440
        ),
    ] = None,
    silver_max_stint: Annotated[
        float | None,
        typer.Option(
            "--silver-max-stint",
            help="Silver continuous minutes.",
            min=1,
            max=1440,
        ),
    ] = None,
    bronze_max_stint: Annotated[
        float | None,
        typer.Option(
            "--bronze-max-stint",
            help="Bronze continuous minutes.",
            min=1,
            max=1440,
        ),
    ] = None,
    silver_min_drive: Annotated[
        float | None,
        typer.Option(
            "--silver-min-drive",
            help="Silver minimum total minutes.",
            min=0,
            max=2880,
        ),
    ] = None,
    bronze_min_drive: Annotated[
        float | None,
        typer.Option(
            "--bronze-min-drive",
            help="Bronze minimum total minutes.",
            min=0,
            max=2880,
        ),
    ] = None,
    driver_max_total: Annotated[
        float | None,
        typer.Option(
            "--driver-max-total",
            help="Maximum total minutes per driver; zero disables.",
            min=0,
            max=2880,
        ),
    ] = None,
) -> None:
    """Update only the supplied current-race values."""
    state: State = ctx.obj
    try:
        config = RaceConfig.from_dict(state.workspace.race_data())
    except (WorkspaceError, ValueError, TypeError) as exc:
        _command_error(state, str(exc))

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
            _command_error(state, "--service-mode must be parallel or sequential")
        config.services_parallel = normalised_mode == "parallel"
    if drivers is not None:
        try:
            config.drivers = _parse_drivers(drivers)
            config.ensure_unique_driver_ids()
        except ValueError as exc:
            _command_error(state, str(exc))

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

    try:
        state.workspace.save_race(config.to_dict(), overwrite=True)
    except (WorkspaceError, OSError) as exc:
        _command_error(state, str(exc))
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
    except (WorkspaceError, ValueError, TypeError) as exc:
        _command_error(state, str(exc))
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


@model_app.command("recommend")
def model_recommend(ctx: typer.Context) -> None:
    """Run read-only local checks and suggest an optional Ollama model."""
    state: State = ctx.obj
    try:
        comparison = compare_strategies(load_preset(DEFAULT_PRESET), iterations=20)
        core_ready = comparison.preferred.plan.is_feasible
        core_detail = (
            f"{comparison.preferred.name}, "
            f"{comparison.preferred.plan.predicted_laps} laps"
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        core_ready = False
        core_detail = str(exc)

    options = [option.to_dict() for option in MODEL_OPTIONS]
    payload = {
        "ok": core_ready,
        "status": "provisional",
        "provider": "ollama-only",
        "catalog_reviewed": CATALOG_REVIEWED,
        "core_check": {
            "status": "pass" if core_ready else "fail",
            "detail": core_detail,
        },
        "operational_default": CORE_ONLY.to_dict(),
        "optional_first_try": FIRST_TRY.to_dict() if core_ready else None,
        "choices": options,
        "pitwall_conformance_tested": False,
        "changes_made": False,
        "downloads_started": False,
        "validation": (
            "Provisional candidate guidance only; Pitwall has not published a "
            "real-model tool-calling conformance benchmark."
        ),
    }
    if state.json_output:
        _print_json(payload)
    else:
        console.print(
            Panel.fit(
                "[bold]Read-only Ollama model guide[/bold]\n"
                "Nothing was downloaded and no setting was changed.",
                border_style="cyan",
            )
        )
        console.print(
            f"Core self-check: {'pass' if core_ready else 'fail'} · {core_detail}"
        )
        table = Table(title="Ollama-only choices")
        table.add_column("Role")
        table.add_column("Model")
        table.add_column("Approx. model storage", justify="right")
        table.add_column("Meaning")
        for option in MODEL_OPTIONS:
            table.add_row(
                option.label,
                option.model or "none",
                f"{option.approximate_model_gb:g} GB",
                option.purpose,
            )
        console.print(table)
        if core_ready:
            console.print(
                "\nCore-only remains the verified operational path. If you choose "
                "optional natural-language routing, first try:"
            )
            console.print(f"  ollama pull {FIRST_TRY.model}")
            console.print(f"  pitwall model use {FIRST_TRY.model}")
        else:
            console.print("\nFix the core check before adding a model.")
        console.print(
            "[yellow]Provisional guidance:[/yellow] the self-check does not test "
            "real-model tool-calling quality or hardware fit."
        )
    if not core_ready:
        raise typer.Exit(code=1)


@model_app.command("list")
def model_list(ctx: typer.Context) -> None:
    """List models already installed in local Ollama."""
    state: State = ctx.obj
    state.workspace.initialise()
    try:
        models = list_local_models(state.workspace.settings())
    except (ProviderError, WorkspaceError, ValueError) as exc:
        _command_error(
            state,
            f"Model configuration is not ready: {exc}. "
            "Run 'pitwall model recommend' for no-download choices.",
        )
    if state.json_output:
        _print_json({"models": models})
        return
    if not models:
        console.print(
            "Ollama is running, but no models are installed. "
            "Run `pitwall model recommend` for storage-aware choices."
        )
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
    try:
        settings = state.workspace.settings()
    except (WorkspaceError, ValueError) as exc:
        _command_error(state, str(exc))
    if not force:
        try:
            models = list_local_models(settings)
        except ProviderError:
            _command_error(state, "Ollama is not running. Start it, or use --force.")
        if name not in models:
            _command_error(
                state,
                f"{name!r} is not installed. Available: "
                f"{', '.join(models) or 'none'}. Run 'pitwall model recommend' "
                "for no-download choices.",
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
    try:
        settings = state.workspace.settings()
    except (WorkspaceError, ValueError) as exc:
        _command_error(state, str(exc))
    state.workspace.save_settings(replace(settings, provider="none", model=""))
    _emit(
        state,
        {"provider": "none", "model": ""},
        "Model layer is off. Deterministic mode remains ready.",
    )


def _guided_init(state: State, *, preset: str, replace_existing: bool) -> None:
    """Walk a beginner through the values Pitwall needs, one question at a time."""
    if preset not in list_presets():
        raise typer.BadParameter(
            f"Unknown preset. Choose from: {', '.join(list_presets())}"
        )
    defaults = preset_defaults(preset)
    console.print(
        Panel.fit(
            "Guided race setup\n"
            "Press Enter to accept the preset default for any question.\n"
            "Nothing is written until you confirm the summary.",
            border_style="cyan",
        )
    )
    console.print(f"[yellow]{REGULATION_NOTICE}[/yellow]\n")

    values: dict[str, Any] = {}
    origins: dict[str, str] = {}
    for field in GUIDED_FIELDS:
        preset_value = defaults[field.key]
        console.print(f"[bold]{field.label}[/bold] ({field.unit})")
        if field.help_text:
            console.print(f"  [dim]{field.help_text}[/dim]")
        console.print(
            f"  [dim]Safe range {field.minimum:g}-{field.maximum:g} {field.unit}. "
            f"{field.unknown_hint(preset_value)}[/dim]"
        )
        while True:
            try:
                raw = Prompt.ask(f"  {field.label}", default="")
            except (EOFError, KeyboardInterrupt):  # pragma: no cover - interactive
                console.print("\nGuided setup cancelled; nothing was written.")
                return
            try:
                value, origin = parse_field(field.key, raw, preset_value)
            except GuidedValueError as exc:
                console.print(f"  [red]{exc}[/red] Please try again.")
                continue
            values[field.key] = value
            origins[field.key] = origin
            break

    problems = cross_check(values)
    if problems:
        console.print("\n[red]These values cannot be planned together:[/red]")
        for problem in problems:
            console.print(f"  • {problem}")
        console.print("Re-run `pitwall init --guided` with corrected values.")
        raise typer.Exit(code=1)

    table = Table(title="Review before writing race.json")
    for column in ("Input", "Value", "Unit", "Where it came from"):
        table.add_column(column)
    for row in summary_rows(values, origins):
        table.add_row(*row)
    console.print(table)
    console.print(
        f"[dim]Values marked '{PRESET_ORIGIN}' are bundled assumptions, "
        "not measurements from your car.[/dim]"
    )
    try:
        confirmed = Confirm.ask("Write this race configuration?", default=True)
    except (EOFError, KeyboardInterrupt):  # pragma: no cover - interactive only
        confirmed = False
    if not confirmed:
        console.print("Nothing was written.")
        return

    try:
        config = build_race_config(values, preset=preset)
        path = state.workspace.save_race(config.to_dict(), overwrite=replace_existing)
    except GuidedValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except WorkspaceError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        state,
        {
            "created": str(path),
            "race": config.to_dict(),
            "origins": origins,
            "regulation_notice": REGULATION_NOTICE,
        },
        (
            f"[green]Current race created:[/green] {config.race_name}\n"
            f"Saved to {path}\nRun `pitwall compare` to rank strategies."
        ),
    )


def _planned_reference(state: State, preset: str, strategy: str) -> dict[str, Any]:
    """Read the deterministic plan that the reported result is compared against."""
    result = build_registry(state.workspace).execute(
        "plan_race", {"preset": preset, "strategy": strategy}
    )
    if not result.ok:
        _command_error(state, result.error or "Could not build the planned reference")
    plan = result.data["plan"]
    return {
        "race_name": plan["race_name"],
        "strategy": result.data["strategy"],
        "laps": float(plan["predicted_laps"]),
        "stops": float(plan["pit_stops"]),
        "fuel_burn_per_lap": round(plan["fuel_used_liters"] / plan["predicted_laps"], 4)
        if plan["predicted_laps"]
        else None,
        "stint_lengths": [int(stint["Laps"]) for stint in plan["stints"]],
    }


def _interactive(state: State) -> None:
    state.workspace.initialise()
    console.print(
        Panel.fit(
            "[bold red]PITWALL AGENT[/bold red]\n"
            "Deterministic race tools · optional local Ollama · no cloud telemetry\n"
            f"[yellow]{PRE_RACE_ONLY_HEADER}[/yellow]\n"
            "[dim]Ask a question, or use /help. Type /exit when finished.[/dim]",
            border_style="red",
        )
    )
    if not state.workspace.race_path.exists():
        console.print(
            "[yellow]No current race is configured.[/yellow] Free-form answers will "
            "clearly use the bundled demo until you run [bold]/setup[/bold]."
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
        command = question
        if command.lower().startswith("pitwall "):
            command = "/" + command[8:].strip()
        command_name, _, command_argument = command.partition(" ")
        command_name = command_name.lower()
        if command_name in {"help", "/help"}:
            _print_interactive_help()
            continue
        if command_name in {"welcome", "/welcome"}:
            _print_welcome_content()
            console.print(
                "[dim]Type /setup when you are ready to enter your race.[/dim]"
            )
            continue
        if command_name in {"setup", "/setup"}:
            _guided_init(
                state,
                preset=DEFAULT_PRESET,
                replace_existing=state.workspace.race_path.exists(),
            )
            continue
        if command_name in {"compare", "/compare"}:
            result = build_registry(state.workspace).execute(
                "compare_race_strategies", {"preset": CURRENT_RACE}
            )
            if result.ok:
                _print_comparison(state, result)
            else:
                console.print(f"[red]Could not compare:[/red] {result.error}")
            continue
        if command_name in {"plan", "/plan"}:
            strategy = command_argument.strip() or "Balanced"
            result = build_registry(state.workspace).execute(
                "plan_race",
                {"preset": CURRENT_RACE, "strategy": strategy},
            )
            if result.ok:
                _print_plan_result(state, result)
            else:
                console.print(f"[red]Could not plan:[/red] {result.error}")
            continue
        if command_name in {"export", "/export"}:
            name = command_argument.strip() or "pit-sheet"
            result = build_registry(state.workspace).execute(
                "export_pit_sheet", {"name": name, "preset": CURRENT_RACE}
            )
            if result.ok:
                console.print(
                    f"[green]Created[/green] {result.data['created']} · "
                    f"{result.data['strategy']}"
                )
            else:
                console.print(f"[red]Not created:[/red] {result.error}")
            continue
        if command_name.startswith("/"):
            console.print(f"Unknown command {command_name!r}. Type /help.")
            continue
        _print_agent_reply(state, agent.ask(question, session_id=session_id))


def _print_interactive_help() -> None:
    table = Table(title="Interactive commands")
    table.add_column("Command")
    table.add_column("What it does")
    for command, purpose in (
        ("/welcome", "Explain the strategy terms"),
        ("/setup", "Create or replace the current race with guided prompts"),
        ("/compare", "Rank the three deterministic strategies"),
        ("/plan [strategy]", "Show a complete plan; default is Balanced"),
        ("/export [name]", "Write a new pit sheet"),
        ("/exit", "Close the session"),
    ):
        table.add_row(command, purpose)
    console.print(table)


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
        _print_tool_json(result)
        return
    _require_ok(result)
    plan = result.data["plan"]
    simulation = result.data["simulation"]
    evidence = result.data["evidence"]
    console.print(f"[yellow]{result.data['pre_race_only']}[/yellow]")
    console.print(
        Panel.fit(
            (
                f"[bold]{result.data['strategy']}[/bold] · "
                f"{plan['predicted_laps']} laps · {plan['pit_stops']} stops · "
                f"{plan['fuel_used_liters']} L\n"
                f"{simulation['laps_p10_label']}: {simulation['laps_p10']} · "
                f"median {simulation['laps_median']} · "
                f"{simulation['laps_p90_label']}: {simulation['laps_p90']}\n"
                f"Input source: {result.data['input_source']}\n"
                f"Evidence {evidence['evidence_level']} · "
                f"{evidence['confidence']} confidence · "
                f"{evidence['evidence_meaning']}\n"
                f"Uncertainty source: {simulation['uncertainty_source']}"
            ),
            title=result.data["preset"],
        )
    )
    columns = (
        "Stint",
        "Driver",
        "Start",
        "End",
        "Laps",
        "Fuel start (L)",
        "Tyre set",
        "Tyre age end",
        "Pit after (s)",
    )
    table = Table(show_header=True)
    for column in columns:
        table.add_column(column)
    for stint in plan["stints"]:
        table.add_row(*(str(stint[column]) for column in columns))
    console.print(table)
    _print_trigger_cards(result.data)
    _print_bullets("Warnings", plan["warnings"], "yellow")
    _print_bullets(
        "Infeasibilities",
        [item["message"] for item in plan["infeasibilities"]],
        "red",
    )
    _print_bullets("Assumptions", plan["assumptions"], "dim")


def _print_bullets(title: str, items: list[str], colour: str) -> None:
    if not items:
        return
    console.print(f"[{colour}]{title}:[/{colour}]")
    for item in items:
        console.print(f"  • {item}")


def _print_trigger_cards(data: dict[str, Any]) -> None:
    cards = data.get("trigger_cards") or []
    if not cards:
        return
    table = Table(title="Trigger cards — what to watch")
    for column in ("Trigger", "Watch", "Reconsider when", "Now", "Status"):
        table.add_column(column)
    for card in cards:
        current = (
            "not measured"
            if card["current_value"] is None
            else f"{card['current_value']:g} {card['unit']}"
        )
        table.add_row(
            card["id"],
            card["metric"],
            _trigger_condition(card),
            current,
            card["status"],
        )
    console.print(table)
    reconsider = [card for card in cards if card["status"] == "RECONSIDER"]
    for card in reconsider:
        console.print(
            f"[yellow]{card['id']}:[/yellow] {card['action_reconsider']} "
            f"Affects: {card['affected_decision']}."
        )
    console.print(f"[dim]{data.get('trigger_card_notice', '')}[/dim]")


def _trigger_condition(card: dict[str, Any]) -> str:
    low = card.get("threshold_low")
    high = card.get("threshold_high")
    unit = str(card.get("unit", "")).strip()
    if low is not None and high is not None:
        return f"outside {low:g}–{high:g} {unit}".strip()
    if high is not None:
        return f"> {high:g} {unit}".strip()
    if low is not None:
        return f"< {low:g} {unit}".strip()
    return "declared window changes"


def _print_comparison(state: State, result: ToolResult) -> None:
    if state.json_output:
        _print_tool_json(result)
        return
    _require_ok(result)
    console.print(f"[yellow]{result.data['pre_race_only']}[/yellow]")
    console.print(
        f"\nRecommendation: [bold green]{result.data['recommendation']}[/bold green]"
    )
    if result.data.get("reason"):
        console.print(f"Why: {result.data['reason']}")
    console.print(f"Input source: [bold]{result.data['input_source']}[/bold]")
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
    labels = result.data["percentile_labels"]
    console.print(
        f"[dim]{labels['P10 laps']} · {labels['P90 laps']}: "
        "plan for P10, do not promise P90.[/dim]"
    )
    evidence = result.data["evidence"]
    console.print(
        f"[dim]Evidence {evidence['evidence_level']} · "
        f"{evidence['confidence']} confidence · {evidence['source']}\n"
        f"{evidence['evidence_meaning']}[/dim]"
    )
    _print_trigger_cards(result.data)


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
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        typer.echo(
            json.dumps(
                {"ok": False, "error": f"JSON output contains an invalid value: {exc}"},
                ensure_ascii=True,
            )
        )
        raise typer.Exit(code=1) from exc
    typer.echo(rendered)


def _command_error(state: State, message: str) -> None:
    """Report a runtime input/state failure without a traceback."""
    if state.json_output:
        _print_json({"ok": False, "error": message})
    else:
        console.print(f"[red]Could not complete the command:[/red] {message}")
    raise typer.Exit(code=1)


def _print_tool_json(result: ToolResult) -> None:
    """Emit a ToolResult while keeping JSON and text process semantics equal."""
    _print_json(result.to_dict())
    if not result.ok:
        raise typer.Exit(code=1)


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
        if not math.isfinite(pace_delta):
            raise ValueError(f"Driver {index} pace delta must be a finite number")
        drivers.append(Driver(fields[0], category, pace_delta))
    if not drivers:
        raise ValueError("At least one driver is required")
    return drivers


if __name__ == "__main__":
    app()
