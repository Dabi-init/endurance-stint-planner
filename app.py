"""
Endurance Race Stint Planner — Streamlit UI
Fuel, tyre and driver-regulation stint planning for endurance racing.
"""

from __future__ import annotations

import json
import traceback
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from engine.models import (
    CATEGORY_COLORS,
    Driver,
    DriverCategory,
    PlanResult,
    RaceConfig,
    format_duration,
)
from engine.planner import (
    DEFAULT_PRESET,
    compute_plan,
    compute_plan_with_tyre_life,
    fuel_limited_laps,
    list_presets,
    load_preset,
)
from engine.circuits import (
    DEFAULT_CIRCUIT_ID,
    apply_circuit_to_config,
    circuit_id_from_display,
    get_circuit,
    list_circuit_names,
)
from engine.regulations import check_compliance
from engine.recommendations import generate_strategy_report
from engine.safety_car import SafetyCarConfig, replan_with_safety_car

APP_VERSION = "1.2.0"
PLOTLY_TEMPLATE = "plotly_dark"

CUSTOM_CSS = """
<style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    div[data-testid="stMetric"] {
        background: #1A1D24;
        border: 1px solid #2D3139;
        border-radius: 8px;
        padding: 12px 16px;
    }
    div[data-testid="stMetric"] label { font-size: 0.8rem; color: #9CA3AF; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-size: 1.5rem; font-weight: 600;
    }
    .app-header { margin-bottom: 0.25rem; }
    .app-tagline { color: #9CA3AF; font-size: 0.95rem; margin-bottom: 1rem; }
    .version-badge {
        display: inline-block; background: #E10600; color: white;
        font-size: 0.7rem; font-weight: 600; padding: 2px 8px;
        border-radius: 4px; margin-left: 8px; vertical-align: middle;
    }
    .export-box {
        background: #1A1D24; border: 1px solid #2D3139;
        border-radius: 8px; padding: 16px; margin-top: 12px;
    }
</style>
"""


@st.cache_data(show_spinner=False)
def cached_compute_plan(config_dict: dict) -> dict:
    config = RaceConfig.from_dict(config_dict)
    result = compute_plan(config)
    return _plan_to_cache(result)


def _plan_to_cache(plan: PlanResult) -> dict:
    return {
        "config": plan.config.to_dict(),
        "stints": [s.to_row() for s in plan.stints],
        "stints_raw": [
            {
                "stint_number": s.stint_number,
                "driver_name": s.driver.name,
                "driver_category": s.driver.category.value,
                "pace_delta_sec": s.driver.pace_delta_sec,
                "start_min": s.start_min,
                "duration_min": s.duration_min,
                "end_min": s.end_min,
                "laps": s.laps,
                "fuel_load_liters": s.fuel_load_liters,
                "fuel_used_liters": s.fuel_used_liters,
                "tyres_new": s.tyres_new,
                "tyre_age_at_start_laps": s.tyre_age_at_start_laps,
                "tyre_age_at_end_laps": s.tyre_age_at_end_laps,
                "limiting_factor": s.limiting_factor,
                "notes": s.notes,
            }
            for s in plan.stints
        ],
        "total_pit_stops": plan.total_pit_stops,
        "total_fuel_used_liters": plan.total_fuel_used_liters,
        "predicted_laps": plan.predicted_laps,
        "time_margin_at_flag_min": plan.time_margin_at_flag_min,
        "infeasibilities": [i.to_dict() for i in plan.infeasibilities],
        "warnings": plan.warnings,
        "stint_sheet": plan.stint_sheet_text(),
    }


def _cache_to_plan(cached: dict) -> PlanResult:
    config = RaceConfig.from_dict(cached["config"])
    from engine.models import Infeasibility, Stint

    stints = []
    for raw in cached.get("stints_raw", []):
        driver = Driver(
            name=raw["driver_name"],
            category=DriverCategory(raw["driver_category"]),
            pace_delta_sec=raw.get("pace_delta_sec", 0.0),
        )
        stints.append(
            Stint(
                stint_number=raw["stint_number"],
                driver=driver,
                start_min=raw["start_min"],
                duration_min=raw["duration_min"],
                laps=raw["laps"],
                fuel_load_liters=raw["fuel_load_liters"],
                fuel_used_liters=raw["fuel_used_liters"],
                tyres_new=raw["tyres_new"],
                tyre_age_at_start_laps=raw.get("tyre_age_at_start_laps", 0),
                limiting_factor=raw.get("limiting_factor", ""),
                notes=raw.get("notes", ""),
            )
        )
    return PlanResult(
        config=config,
        stints=stints,
        total_pit_stops=cached["total_pit_stops"],
        total_fuel_used_liters=cached["total_fuel_used_liters"],
        predicted_laps=cached["predicted_laps"],
        time_margin_at_flag_min=cached["time_margin_at_flag_min"],
        infeasibilities=[
            Infeasibility(**i) for i in cached.get("infeasibilities", [])
        ],
        warnings=cached.get("warnings", []),
    )


def _planning_fingerprint(cfg: dict) -> str:
    """Fingerprint plan-affecting inputs (ignore cosmetic labels)."""
    drivers = [
        {"category": d.get("category"), "pace_delta_sec": d.get("pace_delta_sec", 0.0)}
        for d in cfg.get("drivers", [])
    ]
    payload = {
        "race_duration_hours": cfg.get("race_duration_hours"),
        "base_lap_time_sec": cfg.get("base_lap_time_sec"),
        "fuel_tank_liters": cfg.get("fuel_tank_liters"),
        "fuel_consumption_per_lap": cfg.get("fuel_consumption_per_lap"),
        "pit_stop_time_loss_sec": cfg.get("pit_stop_time_loss_sec"),
        "refuel_rate_liters_per_sec": cfg.get("refuel_rate_liters_per_sec"),
        "tyre_life_laps": cfg.get("tyre_life_laps"),
        "tyre_change_time_sec": cfg.get("tyre_change_time_sec"),
        "circuit_id": cfg.get("circuit_id"),
        "regulations": cfg.get("regulations"),
        "drivers": drivers,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _recompute_plan(cfg: dict, *, clear_sc: bool = True) -> None:
    st.session_state.plan_cache = cached_compute_plan(cfg)
    st.session_state.plan_fingerprint = _planning_fingerprint(cfg)
    st.session_state.tyre_life_override = int(cfg.get("tyre_life_laps", 28))
    if clear_sc:
        st.session_state.sc_comparison = None


def _apply_circuit_to_session(circuit_id: str, *, recompute: bool = True) -> None:
    circuit = get_circuit(circuit_id)
    if not circuit:
        return
    cfg = apply_circuit_to_config(st.session_state.config_dict, circuit)
    st.session_state.config_dict = cfg
    st.session_state.circuit_id = circuit_id
    st.session_state.tyre_life_override = int(cfg["tyre_life_laps"])
    if recompute:
        _recompute_plan(cfg)


def _init_session() -> None:
    if "initialized" not in st.session_state:
        preset = DEFAULT_PRESET
        config = load_preset(preset)
        st.session_state.initialized = True
        st.session_state.preset = preset
        st.session_state.config_dict = config.to_dict()
        st.session_state.drivers_data = [d.to_dict() for d in config.drivers]
        st.session_state.circuit_id = DEFAULT_CIRCUIT_ID
        _apply_circuit_to_session(DEFAULT_CIRCUIT_ID, recompute=True)
        st.session_state.sc_comparison = None
        st.session_state.plan_fingerprint = _planning_fingerprint(
            st.session_state.config_dict
        )


def _category_color(category: str) -> str:
    try:
        return CATEGORY_COLORS[DriverCategory(category)]
    except (KeyError, ValueError):
        return "#6C757D"


def _build_timeline_figure(plan: PlanResult, title: str) -> go.Figure:
    if not plan.stints:
        fig = go.Figure()
        fig.update_layout(
            title=title, template=PLOTLY_TEMPLATE,
            paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
            height=200,
        )
        fig.add_annotation(text="No stints to display", showarrow=False)
        return fig

    rows = []
    for stint in plan.stints:
        rows.append({
            "Task": f"S{stint.stint_number} — {stint.driver.name}",
            "Start": stint.start_min,
            "Finish": stint.end_min,
            "Driver": stint.driver.name,
            "Category": stint.driver.category.value,
            "Laps": stint.laps,
            "Fuel (L)": round(stint.fuel_used_liters, 1),
            "Tyres": "New" if stint.tyres_new else "Used",
            "Limit": stint.limiting_factor,
            "Stint": stint.stint_number,
        })

    df = pd.DataFrame(rows)
    color_map = {c.value: _category_color(c.value) for c in DriverCategory}
    epoch = pd.Timestamp("2020-01-01")
    df["Start_dt"] = epoch + pd.to_timedelta(df["Start"], unit="m")
    df["Finish_dt"] = epoch + pd.to_timedelta(df["Finish"], unit="m")

    fig = px.timeline(
        df,
        x_start="Start_dt",
        x_end="Finish_dt",
        y="Task",
        color="Category",
        color_discrete_map=color_map,
        hover_data=["Driver", "Laps", "Fuel (L)", "Tyres", "Limit"],
        title=title,
    )
    race_end = plan.config.race_duration_min
    fig.add_vline(
        x=epoch + pd.Timedelta(minutes=race_end),
        line_dash="dot", line_color="#9CA3AF", opacity=0.6,
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="#0E1117",
        plot_bgcolor="#1A1D24",
        height=max(280, len(plan.stints) * 42 + 120),
        xaxis_title="Race Time (minutes from start)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=20, r=20, t=60, b=40),
    )
    fig.update_xaxes(
        tickformat="%M:%S",
        range=[
            epoch,
            epoch + pd.Timedelta(minutes=race_end * 1.02),
        ],
    )
    return fig


def _driver_compliance_chart(plan: PlanResult) -> go.Figure:
    report = check_compliance(plan)
    config = plan.config
    regs = config.regulations
    race_min = config.race_duration_min

    names, totals, colors = [], [], []
    for dc in report.driver_results:
        names.append(dc.driver.name)
        totals.append(dc.total_drive_min)
        colors.append(_category_color(dc.driver.category.value))

    fig = go.Figure()
    fig.add_bar(
        x=totals, y=names, orientation="h",
        marker_color=colors, name="Drive time",
        hovertemplate="%{y}: %{x:.0f} min<extra></extra>",
    )

    bronze_min = regs.bronze_min_drive_min
    if bronze_min > 0:
        fig.add_vline(
            x=bronze_min, line_dash="dash", line_color="#F4A261",
            annotation_text="Bronze min", annotation_position="top",
        )
    if regs.max_total_drive_min > 0:
        fig.add_vline(
            x=regs.max_total_drive_min, line_dash="dash", line_color="#E10600",
            annotation_text="Max drive", annotation_position="top",
        )

    fig.add_vrect(
        x0=0, x1=race_min, fillcolor="#2D3139", opacity=0.15,
        layer="below", line_width=0,
    )
    fig.update_layout(
        title="Total Drive Time per Driver",
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="#0E1117",
        plot_bgcolor="#1A1D24",
        height=max(220, len(names) * 50 + 100),
        xaxis_title="Minutes",
        yaxis_title="",
        margin=dict(l=20, r=20, t=50, b=40),
    )
    return fig


def _tyre_strategy_chart(plan: PlanResult, tyre_life: int) -> go.Figure:
    if not plan.stints:
        return go.Figure()

    stints = list(range(1, len(plan.stints) + 1))
    stint_laps = [s.laps for s in plan.stints]
    tyre_ages = [s.tyre_age_at_end_laps for s in plan.stints]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=stints, y=stint_laps, name="Stint length (laps)",
        marker_color="#457B9D",
    ))
    fig.add_trace(go.Scatter(
        x=stints, y=tyre_ages, name="Tyre age at stint end",
        mode="lines+markers", line=dict(color="#F4A261", width=2),
    ))
    fig.add_hline(
        y=tyre_life, line_dash="dash", line_color="#E10600",
        annotation_text=f"Tyre life cap ({tyre_life} laps)",
    )
    fig.update_layout(
        title="Stint Length vs Tyre Age",
        template=PLOTLY_TEMPLATE,
        paper_bgcolor="#0E1117",
        plot_bgcolor="#1A1D24",
        xaxis_title="Stint #",
        yaxis_title="Laps",
        barmode="group",
        height=360,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def _render_infeasibility_cards(plan: PlanResult) -> None:
    if not plan.infeasibilities:
        return
    st.error("Strategy is infeasible with the current inputs.")
    for issue in plan.infeasibilities:
        with st.container():
            st.markdown(f"**{issue.message}**")
            if issue.suggestion:
                st.caption(f"Suggested fix: {issue.suggestion}")


def _sidebar_config() -> RaceConfig:
    st.sidebar.header("Race Setup")

    presets = list_presets()
    default_idx = presets.index(DEFAULT_PRESET) if DEFAULT_PRESET in presets else 0
    preset = st.sidebar.selectbox(
        "Preset",
        presets,
        index=default_idx,
        help="Load a championship-ready parameter set. Changing preset auto-computes.",
    )

    if preset != st.session_state.get("preset"):
        config = load_preset(preset)
        st.session_state.preset = preset
        st.session_state.config_dict = config.to_dict()
        st.session_state.drivers_data = [d.to_dict() for d in config.drivers]
        circuit_id = st.session_state.get("circuit_id", DEFAULT_CIRCUIT_ID)
        with st.spinner("Computing strategy…"):
            _apply_circuit_to_session(circuit_id, recompute=True)

    cfg = st.session_state.config_dict
    regs = cfg.get("regulations", {})

    circuit_names = list_circuit_names()
    current_circuit = get_circuit(st.session_state.get("circuit_id", DEFAULT_CIRCUIT_ID))
    current_display = current_circuit.display_name if current_circuit else circuit_names[0]
    circuit_display = st.sidebar.selectbox(
        "Circuit",
        circuit_names,
        index=circuit_names.index(current_display) if current_display in circuit_names else 0,
        help="Track profile adjusts lap time, tyre life, fuel use, and pit loss.",
    )
    selected_circuit_id = circuit_id_from_display(circuit_display)
    if selected_circuit_id and selected_circuit_id != st.session_state.get("circuit_id"):
        with st.spinner("Applying circuit profile…"):
            _apply_circuit_to_session(selected_circuit_id, recompute=True)

    if current_circuit:
        st.sidebar.caption(
            f"{current_circuit.length_km:.3f} km · "
            f"Tyre wear: **{current_circuit.tyre_wear}** · "
            f"SC risk: **{current_circuit.sc_risk}**"
        )

    with st.sidebar.expander("Race Parameters", expanded=True):
        cfg["race_name"] = st.text_input(
            "Race name", value=cfg.get("race_name", ""),
            help="Label for exports and pit-wall printouts.",
        )
        cfg["race_duration_hours"] = st.number_input(
            "Race duration (hours)", min_value=0.5, max_value=48.0,
            value=float(cfg.get("race_duration_hours", 6.0)), step=0.5,
            help="Total elapsed race time from green flag to chequered flag.",
        )
        cfg["base_lap_time_sec"] = st.number_input(
            "Base lap time (seconds)", min_value=30.0, max_value=300.0,
            value=float(cfg.get("base_lap_time_sec", 120.0)), step=0.5,
            help="Reference lap time at race fuel — used for stint duration geometry.",
        )

    with st.sidebar.expander("Car & Fuel"):
        cfg["fuel_tank_liters"] = st.number_input(
            "Fuel tank (L)", min_value=10.0, max_value=200.0,
            value=float(cfg.get("fuel_tank_liters", 100.0)), step=1.0,
            help="Maximum fuel capacity per stint start.",
        )
        cfg["fuel_consumption_per_lap"] = st.number_input(
            "Fuel per lap (L)", min_value=0.1, max_value=10.0,
            value=float(cfg.get("fuel_consumption_per_lap", 2.9)), step=0.1,
            format="%.2f",
            help="Average fuel burn per racing lap under green-flag conditions.",
        )
        regs["fuel_safety_laps"] = st.number_input(
            "Fuel safety laps", min_value=0, max_value=5,
            value=int(regs.get("fuel_safety_laps", 1)),
            help="Reserve fuel held back each stint (not used for lap count).",
        )

    with st.sidebar.expander("Tyres"):
        cfg["tyre_life_laps"] = st.number_input(
            "Tyre life (laps)", min_value=1, max_value=80,
            value=int(cfg.get("tyre_life_laps", 28)),
            help="Recommended maximum laps per tyre set before performance cliff.",
        )
        cfg["tyre_change_time_sec"] = st.number_input(
            "Tyre change time (s)", min_value=0.0, max_value=120.0,
            value=float(cfg.get("tyre_change_time_sec", 0.0)), step=1.0,
            help="Additional pit time when fitting a fresh tyre set.",
        )
        regs["change_tyres_every_stop"] = st.checkbox(
            "Change tyres every stop",
            value=bool(regs.get("change_tyres_every_stop", True)),
            help="If enabled, tyre change time is added to each pit stop.",
        )

    with st.sidebar.expander("Pit Stops"):
        cfg["pit_stop_time_loss_sec"] = st.number_input(
            "Pit lane time loss (s)", min_value=10.0, max_value=180.0,
            value=float(cfg.get("pit_stop_time_loss_sec", 55.0)), step=1.0,
            help="Total time lost per stop: entry, stationary work, and exit.",
        )
        cfg["refuel_rate_liters_per_sec"] = st.number_input(
            "Refuel rate (L/s)", min_value=0.5, max_value=10.0,
            value=float(cfg.get("refuel_rate_liters_per_sec", 2.5)), step=0.1,
            help="Fuel flow rate during stationary refuelling.",
        )

    with st.sidebar.expander("Drivers"):
        drivers_data = st.session_state.drivers_data
        updated_drivers = []
        remove_idx: Optional[int] = None

        for i, d in enumerate(drivers_data):
            st.markdown(f"**Driver {i + 1}**")
            name = st.text_input("Name", value=d.get("name", f"Driver {i+1}"), key=f"dname_{i}")
            category = st.selectbox(
                "Category", [c.value for c in DriverCategory],
                index=[c.value for c in DriverCategory].index(d.get("category", "Pro")),
                key=f"dcat_{i}",
            )
            pace = st.number_input(
                "Pace delta (s)", min_value=-5.0, max_value=10.0,
                value=float(d.get("pace_delta_sec", 0.0)), step=0.1,
                key=f"dpace_{i}",
                help="Lap time offset vs base pace. Positive = slower.",
            )
            if st.button("Remove", key=f"drem_{i}") and len(drivers_data) > 1:
                remove_idx = i
            updated_drivers.append({
                "name": name, "category": category, "pace_delta_sec": pace,
            })

        if remove_idx is not None:
            updated_drivers.pop(remove_idx)
            st.session_state.drivers_data = updated_drivers
            st.rerun()

        if st.button("+ Add driver") and len(updated_drivers) < 6:
            updated_drivers.append({
                "name": f"Driver {len(updated_drivers) + 1}",
                "category": "Silver",
                "pace_delta_sec": 0.5,
            })
            st.session_state.drivers_data = updated_drivers
            st.rerun()

        cfg["drivers"] = updated_drivers
        st.session_state.drivers_data = updated_drivers

    with st.sidebar.expander("Regulations"):
        regs["pro_max_continuous_stint_min"] = st.number_input(
            "Pro max stint (min)", min_value=15.0, max_value=240.0,
            value=float(regs.get("pro_max_continuous_stint_min", 120.0)),
            help="Maximum continuous driving time for Pro-rated drivers.",
        )
        regs["silver_max_continuous_stint_min"] = st.number_input(
            "Silver max stint (min)", min_value=15.0, max_value=240.0,
            value=float(regs.get("silver_max_continuous_stint_min", 90.0)),
        )
        regs["bronze_max_continuous_stint_min"] = st.number_input(
            "Bronze max stint (min)", min_value=15.0, max_value=240.0,
            value=float(regs.get("bronze_max_continuous_stint_min", 65.0)),
        )
        regs["bronze_min_drive_min"] = st.number_input(
            "Bronze min drive (min)", min_value=0.0, max_value=720.0,
            value=float(regs.get("bronze_min_drive_min", 120.0)),
            help="Minimum total driving time required for Bronze drivers (e.g. 2h in 6h).",
        )
        regs["silver_min_drive_min"] = st.number_input(
            "Silver min drive (min)", min_value=0.0, max_value=720.0,
            value=float(regs.get("silver_min_drive_min", 0.0)),
        )
        regs["max_total_drive_min"] = st.number_input(
            "Max total drive / driver (min)", min_value=0.0, max_value=1440.0,
            value=float(regs.get("max_total_drive_min", 0.0)),
            help="0 = no cap. Used in 24h races to limit individual driver exposure.",
        )

    cfg["regulations"] = regs
    st.session_state.config_dict = cfg

    fp = _planning_fingerprint(cfg)
    if fp != st.session_state.get("plan_fingerprint"):
        with st.spinner("Updating strategy…"):
            _recompute_plan(cfg)

    compute_clicked = st.sidebar.button(
        "Recompute Plan", type="primary", use_container_width=True,
        help="Force a fresh calculation (also runs automatically when inputs change).",
    )
    if compute_clicked:
        with st.spinner("Computing strategy…"):
            _recompute_plan(cfg)

    plan = _cache_to_plan(st.session_state.plan_cache)
    status = "Ready" if plan.is_feasible else "Infeasible — see Stint Plan"
    st.sidebar.caption(f"Plan status: **{status}**")

    return RaceConfig.from_dict(cfg)


def _render_strategy_briefing(plan: PlanResult, config: RaceConfig) -> None:
    """Compact strategy briefing — folded into Stint Plan tab."""
    circuit_id = st.session_state.get("circuit_id", config.circuit_id or DEFAULT_CIRCUIT_ID)
    report = generate_strategy_report(plan, circuit_id)

    with st.expander("Strategy briefing & calculated metrics", expanded=False):
        if report.circuit:
            st.caption(f"{report.circuit.name} — {report.circuit.characteristics}")
        if plan.is_feasible:
            st.markdown(report.race_approach_summary)
            m = report.metrics
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Avg stint", f"{m.avg_stint_laps:.0f} laps")
            r2.metric("Limiting factor", m.limiting_factor)
            r3.metric("Fuel / tyre gap", f"{m.fuel_tyre_gap_laps} laps")
            r4.metric("Est. deg / lap", f"{m.estimated_deg_per_lap_sec:.2f}s")
            for insight in report.insights[:4]:
                st.markdown(f"{insight.icon()} **{insight.title}** — {insight.detail}")
        else:
            st.info("Resolve infeasibility issues to unlock full recommendations.")
        st.caption(
            "Metrics are calculated from plan inputs, not live telemetry. "
            "Future versions may import session data for calibration."
        )


def _tab_stint_plan(plan: PlanResult, cached: dict, config: RaceConfig) -> None:
    if not plan.is_feasible:
        _render_infeasibility_cards(plan)
        if not plan.stints:
            return
        st.warning("Partial plan shown — adjust inputs using the suggested fixes above.")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total stints", len(plan.stints))
    c2.metric("Pit stops", plan.total_pit_stops)
    c3.metric("Fuel used", f"{plan.total_fuel_used_liters:.0f} L")
    c4.metric("Predicted laps", plan.predicted_laps)
    c5.metric(
        "Margin at flag",
        format_duration(plan.time_margin_at_flag_min),
    )

    if plan.stints:
        st.plotly_chart(
            _build_timeline_figure(plan, "Stint Timeline"),
            use_container_width=True,
        )

    _render_strategy_briefing(plan, config)

    if not cached.get("stints"):
        return

    df = pd.DataFrame(cached["stints"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown('<div class="export-box">', unsafe_allow_html=True)
    st.subheader("Export")
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "Download CSV",
            data=df.to_csv(index=False),
            file_name="stint_plan.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_b:
        st.download_button(
            "Download Stint Sheet",
            data=cached["stint_sheet"],
            file_name="stint_sheet.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _tab_driver_compliance(plan: PlanResult) -> None:
    if not plan.is_feasible:
        _render_infeasibility_cards(plan)
        return

    st.plotly_chart(_driver_compliance_chart(plan), use_container_width=True)

    report = check_compliance(plan)
    rows = []
    for dc in report.driver_results:
        for check in dc.checks:
            rows.append({
                "Driver": dc.driver.name,
                "Category": dc.driver.category.value,
                "Rule": check.rule_text,
                "Status": check.status_icon(),
                "Detail": check.detail,
            })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if report.stint_violations:
        st.error("Continuous stint violations detected:")
        for v in report.stint_violations:
            st.markdown(f"- {v}")

    if not report.all_passed:
        st.warning(
            "One or more regulation checks failed. "
            "Adjust driver rotation or regulation limits in the sidebar."
        )


def _tab_tyre_strategy(plan: PlanResult, config: RaceConfig) -> None:
    tyre_life = st.slider(
        "Tyre life assumption (laps)",
        min_value=5, max_value=60,
        value=int(st.session_state.get("tyre_life_override", config.tyre_life_laps)),
        help="Live what-if: adjust tyre life and see impact on stint count.",
    )
    st.session_state.tyre_life_override = tyre_life

    tyre_plan = compute_plan_with_tyre_life(config, tyre_life)

    fuel_laps = fuel_limited_laps(config)
    col1, col2, col3 = st.columns(3)
    col1.metric("Fuel-limited laps", fuel_laps)
    col2.metric("Tyre life (assumed)", tyre_life)
    limiting = "Fuel" if fuel_laps < tyre_life else ("Tyre" if tyre_laps < fuel_laps else "Equal")
    col3.metric("Limiting factor", limiting)

    if tyre_plan.is_feasible:
        sets_used = sum(1 for s in tyre_plan.stints if s.tyres_new)
        avg_age = (
            sum(s.tyre_age_at_end_laps for s in tyre_plan.stints) / len(tyre_plan.stints)
            if tyre_plan.stints else 0
        )
        st.metric("Tyre sets used", sets_used)
        st.metric("Avg tyre age at stint end", f"{avg_age:.1f} laps")
        st.plotly_chart(
            _tyre_strategy_chart(tyre_plan, tyre_life),
            use_container_width=True,
        )
        st.caption(
            f"Recomputed: {len(tyre_plan.stints)} stints, "
            f"{tyre_plan.total_pit_stops} pit stops."
        )
    else:
        _render_infeasibility_cards(tyre_plan)


def _tab_safety_car(plan: PlanResult, config: RaceConfig) -> None:
    if not plan.is_feasible:
        _render_infeasibility_cards(plan)
        st.info("Fix the base plan before running Safety Car what-if.")
        return

    race_min = config.race_duration_min
    st.subheader("Safety Car Scenario")

    c1, c2, c3 = st.columns(3)
    with c1:
        deploy = st.slider(
            "SC deployment (min from start)",
            min_value=0.0, max_value=max(race_min - 1.0, 1.0),
            value=min(race_min * 0.35, race_min - 30.0),
            step=1.0,
        )
    with c2:
        duration = st.slider(
            "SC duration (minutes)",
            min_value=0.0, max_value=min(60.0, race_min),
            value=min(15.0, race_min * 0.1),
            step=1.0,
        )
    with c3:
        multiplier = st.slider(
            "Lap time multiplier under SC",
            min_value=1.0, max_value=3.0, value=1.4, step=0.05,
            help="Pace loss factor while Safety Car is on track.",
        )

    sc_pit_loss = st.number_input(
        "Pit loss under SC (seconds)", min_value=5.0, max_value=120.0, value=25.0,
        help="Reduced stationary time when pitting under Safety Car.",
    )

    if st.button("Replan with Safety Car", type="primary"):
        with st.spinner("Computing SC strategy…"):
            sc = SafetyCarConfig(
                deploy_min=deploy,
                duration_min=duration,
                lap_time_multiplier=multiplier,
                sc_pit_loss_sec=sc_pit_loss,
            )
            st.session_state.sc_comparison = replan_with_safety_car(plan, sc)

    comparison = st.session_state.get("sc_comparison")
    if comparison is None:
        st.info("Configure SC parameters and click **Replan with Safety Car**.")
        return

    st.plotly_chart(
        _build_timeline_figure(comparison.original, "Original Plan"),
        use_container_width=True,
    )
    st.plotly_chart(
        _build_timeline_figure(comparison.replanned, "Re-planned (Safety Car)"),
        use_container_width=True,
    )

    d1, d2, d3 = st.columns(3)
    delta = comparison.time_delta_min
    d1.metric(
        "Time delta (margin)",
        format_duration(abs(delta)),
        delta=f"{'+' if delta >= 0 else '-'}{format_duration(abs(delta))}",
    )
    d2.metric("Fuel delta", f"{comparison.fuel_saved_liters:+.1f} L")
    d3.metric("Pit stops moved", len(comparison.pit_stops_moved))

    if comparison.notes:
        st.markdown("**Summary**")
        for note in comparison.notes:
            st.markdown(f"- {note}")


def _tab_methodology() -> None:
    st.markdown("""
## Model Assumptions

This planner uses a **deterministic, green-flag geometry model**:

- **Fuel**: Constant consumption per lap. Stint lap count =
  `floor((tank − safety_reserve) / consumption)`.
- **Tyres**: Linear life cap in laps. Fresh set each stop when enabled.
- **Pit stops**: Fixed time loss plus optional tyre-change duration.
  Refuel rate is modelled but does not extend stationary time beyond
  configured pit loss (conservative).
- **Pace**: Each driver applies a fixed lap-time delta vs. the base lap.
- **Driver rotation**: Greedy selection favouring drivers below minimum
  drive quotas, then round-robin.
- **Circuits**: Six GT/endurance profiles adjust lap time, tyre life,
  fuel consumption, and pit loss. High-wear tracks shorten stints automatically.

## What This Model Does NOT Simulate

| Factor | Status |
|--------|--------|
| Traffic / class traffic | Not modelled |
| Weather / track evolution | Not modelled |
| Gap / position vs. competitors | Not modelled |
| FCY vs full Safety Car procedures | Not modelled |
| Driver fatigue or pace degradation | Not modelled |
| Compulsory driver-change windows (series-specific) | Roadmap |
| Live telemetry / session data import | Roadmap |

## Regulation Model

Inspired by **FIA GT endurance driver categorisation** (Pro / Silver / Bronze):

- Per-category maximum continuous stint time
- Bronze (and optionally Silver) minimum total drive time
- Optional maximum total drive per driver (24h exposure limits)

Compliance is checked after planning. Infeasible configurations return
structured reasons — the app never crashes on bad inputs.

## Validation — Predicted vs. Actual

*Placeholder rows — fill with your race data.*

| Race | Predicted stints | Actual stints | Predicted stops | Actual stops | Notes |
|------|-----------------|---------------|-----------------|--------------|-------|
| _6h Spa 2025 — #42_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _Add stint sheet_ |
| _4h Portimão 2025 — #07_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _Add stint sheet_ |
| _24h Nürburgring 2025 — #118_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _Add stint sheet_ |

---

### About

**Built by Sreenath** — endurance race strategy portfolio project.

- Email: _your.email@example.com_
- LinkedIn: _linkedin.com/in/yourprofile_
- GitHub: [github.com/Dabi-init/endurance-stint-planner](https://github.com/Dabi-init/endurance-stint-planner)
    """)


def main() -> None:
    st.set_page_config(
        page_title="Endurance Race Stint Planner",
        page_icon="🏁",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    _init_session()

    st.markdown(
        '<div class="app-header"><h1>Endurance Race Stint Planner'
        f'<span class="version-badge">v{APP_VERSION}</span></h1></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="app-tagline">Fuel, tyre and driver-regulation stint planning '
        "for endurance racing</p>",
        unsafe_allow_html=True,
    )

    try:
        config = _sidebar_config()
        cached = st.session_state.plan_cache
        plan = _cache_to_plan(cached)

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Stint Plan",
            "Driver Compliance",
            "Tyre Strategy",
            "What-If / Safety Car",
            "Methodology",
        ])

        with tab1:
            _tab_stint_plan(plan, cached, config)
        with tab2:
            _tab_driver_compliance(plan)
        with tab3:
            _tab_tyre_strategy(plan, config)
        with tab4:
            _tab_safety_car(plan, config)
        with tab5:
            _tab_methodology()

    except Exception:
        st.error(
            "Something went wrong computing this plan — try adjusting inputs."
        )
        with st.expander("Technical details"):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()