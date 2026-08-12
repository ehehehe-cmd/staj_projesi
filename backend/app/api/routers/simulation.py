"""``POST /api/simulation/{start,pause,resume,step,stop}``,
``GET /api/simulation/status`` — TASARIM.md §4, §7.

Bu router ``simulation/control.py``'nin (Faz 5) ince bir HTTP sarmalayıcısıdır
— hiçbir state BURADA tutulmaz, hiçbir karar BURADA verilmez (İlke 3: API
süreci ile canlı motor yalnızca DB üzerinden konuşur). ``POST /start``
yalnızca ``simulation_runs`` satırını açar; kararları FİİLEN üreten
``live_engine.py`` süreci AYRI çalışır ve bu satırı kendi döngüsünde
(``run_loop``/``watch_and_run``, bkz. §12.7) yakalar.

TASARIM.md §0.2 "tek operatörlük" varsayımıyla tutarlı olarak, pause/resume/
stop/step İSTEĞE bir ``run_id`` GEREKTİRMEZ — her zaman "durdurulmamış son
oturum" üzerinde çalışır (``control.py``'nin zaten yalnızca TEK aktif
oturuma izin vermesiyle simetrik, bkz. Faz 5 §12.6 karar #2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import SimulationRunOut, SimulationStartRequest
from app.core.config import settings
from app.db import crud
from app.simulation import control
from app.simulation.inference import NoActiveModelError, load_active_models

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


def _current_run_or_404(db: Session):
    run = crud.get_latest_simulation_run(db)
    if run is None:
        raise HTTPException(status_code=404, detail="hiç simulation_run oluşturulmamış")
    return run


@router.get("/status", response_model=SimulationRunOut | None)
def get_status(db: Session = Depends(get_db)) -> SimulationRunOut | None:
    return crud.get_latest_simulation_run(db)


@router.post("/start", response_model=SimulationRunOut)
def start(body: SimulationStartRequest, db: Session = Depends(get_db)) -> SimulationRunOut:
    try:
        models = load_active_models(db)
    except NoActiveModelError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        run = control.start(
            db,
            mode=body.mode,
            tick_interval_ms=body.tick_interval_ms or settings.default_tick_ms,
            manager_model_version_id=models.manager_model_version_id,
            worker_model_version_id=models.worker_model_version_id,
            config=body.config,
        )
    except control.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return run


@router.post("/pause", response_model=SimulationRunOut)
def pause(db: Session = Depends(get_db)) -> SimulationRunOut:
    run = _current_run_or_404(db)
    try:
        result = control.pause(db, run.id)
    except control.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/resume", response_model=SimulationRunOut)
def resume(db: Session = Depends(get_db)) -> SimulationRunOut:
    run = _current_run_or_404(db)
    try:
        result = control.resume(db, run.id)
    except control.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/stop", response_model=SimulationRunOut)
def stop(db: Session = Depends(get_db)) -> SimulationRunOut:
    run = _current_run_or_404(db)
    try:
        result = control.stop(db, run.id)
    except control.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result


@router.post("/step", status_code=202)
def step(db: Session = Depends(get_db)) -> dict:
    run = _current_run_or_404(db)
    try:
        control.request_step(db, run.id)
    except control.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"detail": "manuel adım talep edildi"}
