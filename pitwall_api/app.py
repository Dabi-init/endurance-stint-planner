"""Local FastAPI app. It binds to loopback and does not upload telemetry."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backtest.harness import run_fixture
from engine.series_config import colour_css, load_setup, setup_to_dict
from historical.cache import CachingTransport, FileCache
from historical.catalogue import F1History
from historical.errors import HistoricalSourceError
from historical.http import HttpxTransport
from pitwall import __version__
from pitwall_api.schemas import (
    BacktestResponse,
    CompareRequest,
    PlanRequest,
    PrepareRequest,
    SafetyCarRequestIn,
)
from pitwall_api.service import (
    RequestError,
    compare,
    create_plan,
    prepare_event,
    safety_car,
)


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

    @app.get("/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "engine": "pitwall", "version": __version__}

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

    return app


app = create_app()
