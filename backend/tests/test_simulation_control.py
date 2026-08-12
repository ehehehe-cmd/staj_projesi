"""simulation/control.py birim testleri — TASARIM.md §7, §12.6.

``simulation_runs`` DB'DEKİ TEK GERÇEK KAYNAK olduğu için (İlke 3, bkz.
``control.py`` modül-üstü yorumu) bu testler tamamen ``db_session``
(savepoint/rollback izolasyonlu) fixture'ı üzerinden çalışır — gerçek
NOTIFY teslimini test etmez (bkz. ``test_notifier.py``), yalnızca
``simulation_runs``/``live_events`` satırlarının doğru yazıldığını
doğrular.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import crud
from app.db.models import LiveEvent
from app.simulation import control


def _start(db_session, **overrides):
    kwargs = dict(
        mode="hybrid", tick_interval_ms=500, manager_model_version_id=None, worker_model_version_id=None,
    )
    kwargs.update(overrides)
    return control.start(db_session, **kwargs)


def _event_types(db_session) -> list[str]:
    rows = db_session.execute(select(LiveEvent).order_by(LiveEvent.id)).scalars().all()
    return [r.event_type for r in rows]


class TestStart:
    def test_autonomous_and_hybrid_modes_start_running(self, db_session):
        assert _start(db_session, mode="autonomous").status == "running"

    def test_hybrid_mode_starts_running(self, db_session):
        assert _start(db_session, mode="hybrid").status == "running"

    def test_manual_mode_starts_paused(self, db_session):
        run = _start(db_session, mode="manual")
        assert run.status == "paused"

    def test_start_emits_simulation_started_event(self, db_session):
        _start(db_session)
        assert "simulation_started" in _event_types(db_session)

    def test_start_rejects_when_an_active_run_already_exists(self, db_session):
        _start(db_session)
        with pytest.raises(control.InvalidTransitionError):
            _start(db_session)

    def test_start_allowed_after_previous_run_was_stopped(self, db_session):
        first = _start(db_session)
        control.stop(db_session, first.id)
        second = _start(db_session)
        assert second.id != first.id
        assert second.status == "running"


class TestPauseResumeStop:
    def test_happy_path_transitions(self, db_session):
        run = _start(db_session)

        control.pause(db_session, run.id)
        assert crud.get_simulation_run(db_session, run.id).status == "paused"
        assert "simulation_paused" in _event_types(db_session)

        control.resume(db_session, run.id)
        assert crud.get_simulation_run(db_session, run.id).status == "running"
        assert "simulation_resumed" in _event_types(db_session)

        control.stop(db_session, run.id)
        stopped = crud.get_simulation_run(db_session, run.id)
        assert stopped.status == "stopped"
        assert stopped.stopped_at is not None
        assert "simulation_stopped" in _event_types(db_session)

    def test_pause_requires_running(self, db_session):
        run = _start(db_session, mode="manual")  # 'paused' başlar
        with pytest.raises(control.InvalidTransitionError):
            control.pause(db_session, run.id)

    def test_resume_requires_paused(self, db_session):
        run = _start(db_session)  # 'running' başlar
        with pytest.raises(control.InvalidTransitionError):
            control.resume(db_session, run.id)

    def test_stop_requires_running_or_paused(self, db_session):
        run = _start(db_session)
        control.stop(db_session, run.id)
        with pytest.raises(control.InvalidTransitionError):
            control.stop(db_session, run.id)

    def test_unknown_run_id_raises(self, db_session):
        with pytest.raises(control.InvalidTransitionError):
            control.pause(db_session, 987654321)


class TestRequestStep:
    def test_request_step_requires_paused(self, db_session):
        run = _start(db_session)  # running
        with pytest.raises(control.InvalidTransitionError):
            control.request_step(db_session, run.id)

    def test_request_step_emits_manual_step_without_changing_status(self, db_session):
        run = _start(db_session, mode="manual")
        control.request_step(db_session, run.id)
        assert crud.get_simulation_run(db_session, run.id).status == "paused"
        assert "manual_step" in _event_types(db_session)
