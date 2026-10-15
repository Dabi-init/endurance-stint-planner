"""Local FastAPI app. It binds to loopback and does not upload telemetry."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backtest.harness import run_fixture
from engine.series_config import colour_css, load_setup, setup_to_dict
from historical.cache import CachingTransport, FileCache
from historical.catalogue import F1History
from historical.errors import HistoricalSourceError
from historical.http import HttpxTransport
from live.sources import LiveSourceError, describe_sources, iter_frames
from pitwall import __version__
from pitwall_api.schemas import (
    BacktestResponse,
    CompareRequest,
    OddsRequest,
    PlanRequest,
    PrepareRequest,
    ReplayRequest,
    SafetyCarRequestIn,
    UndercutRequest,
)
from pitwall_api.service import (
    RequestError,
    compare,
    create_plan,
    f1_odds,
    f1_undercut,
    prepare_event,
    safety_car,
)
from replay.session import build_replay

STATIC_DIR = Path(__file__).resolve().parent / "static"


def default_source(cache_dir: Path | None = None) -> F1History:
    root = cache_dir or Path.cwd() / ".cache" / "pitwall-historical"
    transport = CachingTransport(HttpxTransport(), FileCache(root))
    return F1History(transport)


def create_app(source: object | None = None) -> FastAPI:
    app = FastAPI(title="Pitwall", version=__version__)
    history = source if source is not None else default_source()

    @app.exception_handler(RequestError)
    async def _request_error(_request: object, exc: RequestError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(HistoricalSourceError)
    async def _historical_error(
        _request: object, exc: HistoricalSourceError
    ) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/")
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine": "pitwall", "version": __version__}

    @app.get("/v1/replays/{fixture_id}")
    def replay_get(fixture_id: str) -> dict[str, object]:
        return _replay(fixture_id, {}, False)

    @app.post("/v1/replays/{fixture_id}")
    def replay_post(fixture_id: str, body: ReplayRequest) -> dict[str, object]:
        return _replay(fixture_id, body.overrides, body.anchor_pace)

    @app.post("/v1/plans")
    def plans(body: PlanRequest):
        return create_plan(body)

    @app.post("/v1/scenarios/compare")
    def scenarios(body: CompareRequest):
        return compare(body)

    @app.post("/v1/safety-car")
    def safety(body: SafetyCarRequestIn):
        return safety_car(body)

    @app.post("/v1/f1/events/{season}/{round_}/prepare")
    def prepare(season: int, round_: int, body: PrepareRequest):
        return prepare_event(season, round_, body, history)

    @app.get("/v1/f1/events/{season}/{round_}")
    def event(season: int, round_: int) -> dict[str, object]:
        try:
            setup = load_setup(season, round_)
        except ValueError as exc:
            raise RequestError(str(exc)) from exc
        return setup_to_dict(setup)

    @app.get("/v1/live/sources")
    def live_sources() -> list[dict[str, object]]:
        return describe_sources()

    @app.get("/v1/live/{source_id}/frames")
    def live_frames(
        source_id: str,
        sc_start: int | None = None,
        sc_end: int | None = None,
        sc_pit: float | None = None,
        sc_kind: str = "safety-car",
    ) -> list[dict[str, object]]:
        return _live_frames(source_id, _safety_query(sc_start, sc_end, sc_pit, sc_kind))

    @app.get("/v1/live/{source_id}/stream")
    def live_stream(
        source_id: str,
        pace_ms: int = 0,
        sc_start: int | None = None,
        sc_end: int | None = None,
        sc_pit: float | None = None,
        sc_kind: str = "safety-car",
    ) -> StreamingResponse:
        frames = _live_frames(
            source_id, _safety_query(sc_start, sc_end, sc_pit, sc_kind)
        )
        delay = pace_delay_sec(pace_ms)

        def generate():
            for frame in frames:
                yield f"data: {json.dumps(frame)}\n\n"
                if delay:
                    time.sleep(delay)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/v1/f1/undercut")
    def undercut_route(body: UndercutRequest) -> dict[str, object]:
        return f1_undercut(body)

    @app.post("/v1/f1/odds")
    def odds_route(body: OddsRequest) -> dict[str, object]:
        return f1_odds(body)

    @app.post("/v1/backtests/{fixture_id}")
    def backtest(fixture_id: str) -> BacktestResponse:
        try:
            report = run_fixture(fixture_id)
        except ValueError as exc:
            raise RequestError(str(exc), status=404) from exc
        return BacktestResponse(
            event_name=report.event_name,
            season=report.season,
            round=report.round,
            driver_number=report.driver_number,
            driver_code=report.driver_code,
            full_name=report.full_name,
            team_name=report.team_name,
            team_colour=report.team_colour,
            team_colour_css=colour_css(report.team_colour),
            headshot_url=report.headshot_url,
            livery_image_url=report.livery_image_url,
            actual_compounds=list(report.actual_compounds),
            actual_stint_laps=list(report.actual_stint_laps),
            actual_stop_laps=list(report.actual_stop_laps),
            actual_pit_durations_sec=list(report.actual_pit_durations_sec),
            actual_race_time_sec=report.actual_race_time_sec,
            predicted_compounds=list(report.predicted_compounds),
            predicted_stint_laps=list(report.predicted_stint_laps),
            predicted_stop_laps=list(report.predicted_stop_laps),
            predicted_race_time_sec=report.predicted_race_time_sec,
            replay_race_time_sec=report.replay_race_time_sec,
            race_time_delta_sec=report.race_time_delta_sec,
            replay_time_delta_sec=report.replay_time_delta_sec,
            stop_count_delta=report.stop_count_delta,
            same_stop_count=report.same_stop_count,
            stint_length_deltas=(
                None
                if report.stint_length_deltas is None
                else list(report.stint_length_deltas)
            ),
            pace_anchor_sec=report.pace_anchor_sec,
            evidence_level=report.evidence_level,
            notes=list(report.notes),
            image_policy=report.image_policy,
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def pace_delay_sec(pace_ms: int) -> float:
    """Cap the replay pause so a caller cannot stall the process for long."""
    return min(max(pace_ms, 0), 2_000) / 1000


def _safety_query(
    sc_start: int | None,
    sc_end: int | None,
    sc_pit: float | None,
    sc_kind: str,
) -> dict[str, object] | None:
    if sc_start is None and sc_end is None and sc_pit is None:
        return None
    if sc_start is None or sc_end is None or sc_pit is None:
        raise RequestError("Safety car needs start_lap, end_lap, and pit_loss_sec.")
    return {
        "kind": sc_kind,
        "start_lap": sc_start,
        "end_lap": sc_end,
        "pit_loss_sec": sc_pit,
        "pull_pit_into_sc": True,
    }


def _live_frames(
    source_id: str, safety_car: dict[str, object] | None
) -> list[dict[str, object]]:
    try:
        return list(iter_frames(source_id, safety_car=safety_car))
    except LiveSourceError as exc:
        raise RequestError(str(exc), status=400) from exc


def _replay(fixture_id: str, overrides: dict, anchor_pace: bool) -> dict[str, object]:
    try:
        script = build_replay(
            fixture_id, overrides=overrides or None, anchor_pace=anchor_pace
        )
    except ValueError as exc:
        raise RequestError(str(exc), status=404) from exc
    return script.payload


app = create_app()
