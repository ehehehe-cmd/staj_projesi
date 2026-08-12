"""run/pause/resume/step/stop state machine — TASARIM.md §7:

    ``simulation/control.py`` bir state machine tutar: RUNNING / PAUSED / STOPPED.

Tasarım kararı (bkz. TASARIM.md §12.6): bu state'i bir Python nesnesinde
BELLEKTE tutmak, İlke 3'ü ("API süreci ile canlı motor birbirine doğrudan
bağlı değildir; yalnızca DB + LISTEN/NOTIFY üzerinden haberleşirler") ihlal
ederdi — API süreci ile motor süreci FARKLI process'lerdir, aralarında
paylaşılan bir bellek yoktur. Bu yüzden ``simulation_runs.status`` DB'DEKİ
TEK GERÇEK KAYNAKTIR; bu modülün fonksiyonları sadece o satırı okur/yazar +
karşılık gelen ``live_events`` satırını (+ NOTIFY) üretir. §4'teki "tüm API
request'leri arasında paylaşılır" ifadesi bu ışıkta okunmalı: paylaşılan şey
bir bellek nesnesi değil, bu DB satırıdır — Faz 6'nın API route'ları da
kendi state'lerini TUTMADAN, sadece bu modülün fonksiyonlarını çağırır.

``request_step`` özel bir durumdur: ``status``'ü DEĞİŞTİRMEZ (PAUSED kalır),
yalnızca ``manual_step`` tipinde bir ``live_events`` satırı + NOTIFY üretir;
motor (``live_engine.run_loop``) bunu ``notifier.py`` üzerinden dinleyip
TEK bir atomik karar (``LiveEngine.step_once``) çalıştırır.

``mode`` (autonomous/manual/hybrid) başlangıç durumunu belirler (TASARIM.md
§12.6'daki yorum kararı): ``manual`` operatörün HER kararı elle tetiklediği
bir oturumdur, bu yüzden ``paused`` başlar; ``autonomous``/``hybrid`` ise
doğrudan ``running`` başlar (ikisi arasındaki fark yalnızca UI/operatör
beklentisidir — state machine'in kendisi aynıdır, her ikisi de istenildiği
an duraklatılabilir/adımlanabilir).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import crud
from app.db.models import SimulationRun


class InvalidTransitionError(RuntimeError):
    """İzin verilmeyen bir durum geçişi istendiğinde (ör. zaten çalışan bir
    oturumu tekrar ``start`` etmeye çalışmak) fırlatılır."""


def start(
    session: Session,
    *,
    mode: str,
    tick_interval_ms: int,
    manager_model_version_id: int,
    worker_model_version_id: int,
    config: dict | None = None,
) -> SimulationRun:
    existing = crud.get_latest_simulation_run(session)
    if existing is not None and existing.status != "stopped":
        raise InvalidTransitionError(
            f"zaten devam eden bir simulation_run var (id={existing.id}, status={existing.status}) "
            "— önce stop() çağrılmalı"
        )
    initial_status = "paused" if mode == "manual" else "running"
    run = crud.create_simulation_run(
        session,
        mode=mode,
        status=initial_status,
        tick_interval_ms=tick_interval_ms,
        manager_model_version_id=manager_model_version_id,
        worker_model_version_id=worker_model_version_id,
        config=config,
    )
    crud.emit_event(session, event_type="simulation_started", payload={"run_id": run.id, "mode": mode})
    return run


def pause(session: Session, run_id: int) -> SimulationRun:
    _require_status(session, run_id, {"running"})
    run = crud.set_simulation_run_status(session, run_id, "paused")
    crud.emit_event(session, event_type="simulation_paused", payload={"run_id": run_id})
    return run


def resume(session: Session, run_id: int) -> SimulationRun:
    _require_status(session, run_id, {"paused"})
    run = crud.set_simulation_run_status(session, run_id, "running")
    crud.emit_event(session, event_type="simulation_resumed", payload={"run_id": run_id})
    return run


def stop(session: Session, run_id: int) -> SimulationRun:
    _require_status(session, run_id, {"running", "paused"})
    run = crud.set_simulation_run_status(session, run_id, "stopped")
    crud.emit_event(session, event_type="simulation_stopped", payload={"run_id": run_id})
    return run


def request_step(session: Session, run_id: int) -> None:
    """PAUSED bir oturumda tek bir atomik kararın çalıştırılmasını talep
    eder — ``status`` PAUSED olarak KALIR (TASARIM.md §7: "/api/simulation/step
    ... çalıştırıp motoru tekrar PAUSED'a döndürür")."""
    _require_status(session, run_id, {"paused"})
    crud.emit_event(session, event_type="manual_step", payload={"run_id": run_id})


def _require_status(session: Session, run_id: int, allowed: set[str]) -> SimulationRun:
    run = crud.get_simulation_run(session, run_id)
    if run is None:
        raise InvalidTransitionError(f"simulation_runs.id={run_id} bulunamadı")
    if run.status not in allowed:
        raise InvalidTransitionError(f"run id={run_id} status={run.status!r}, beklenen: {sorted(allowed)}")
    return run
