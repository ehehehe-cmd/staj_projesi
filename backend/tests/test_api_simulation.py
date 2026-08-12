"""``api/routers/simulation.py`` testleri — TASARIM.md §4, §7, §12.7.

Gerçek aktif model (``model_versions.id=89``/``90``) ``db_session``
transaction'ı içinde zaten görünür olduğu için ``start`` normal koşulda
bunları kullanır — canlı/geçerli bir checkpoint gerektiren tek testin
(``NoActiveModelError`` yolu) DIŞINDA ayrı bir sahte model kaydına gerek
YOKTUR.
"""

from __future__ import annotations

from sqlalchemy import update

from app.db import crud
from app.db.models import ModelVersion


class TestStatus:
    def test_no_run_yet_returns_null(self, api_client, db_session):
        r = api_client.get("/api/simulation/status")
        assert r.status_code == 200
        assert r.json() is None


class TestStart:
    def test_start_creates_a_running_session_using_active_models(self, api_client, db_session):
        r = api_client.post("/api/simulation/start", json={"mode": "hybrid", "tick_interval_ms": 250})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "running"
        assert body["mode"] == "hybrid"
        assert body["manager_model_version_id"] == 89
        assert body["worker_model_version_id"] == 90

        status = api_client.get("/api/simulation/status").json()
        assert status["id"] == body["id"]

    def test_manual_mode_starts_paused(self, api_client, db_session):
        r = api_client.post("/api/simulation/start", json={"mode": "manual"})
        assert r.json()["status"] == "paused"

    def test_start_rejects_when_a_session_is_already_running(self, api_client, db_session):
        api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        r2 = api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        assert r2.status_code == 409

    def test_start_without_active_model_returns_409(self, api_client, db_session):
        db_session.execute(update(ModelVersion).values(is_active=False))
        db_session.flush()
        r = api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        assert r.status_code == 409


class TestPauseResumeStopStep:
    def test_happy_path(self, api_client, db_session):
        run = api_client.post("/api/simulation/start", json={"mode": "hybrid"}).json()

        r_pause = api_client.post("/api/simulation/pause")
        assert r_pause.status_code == 200
        assert r_pause.json()["status"] == "paused"

        r_step = api_client.post("/api/simulation/step")
        assert r_step.status_code == 202

        r_resume = api_client.post("/api/simulation/resume")
        assert r_resume.status_code == 200
        assert r_resume.json()["status"] == "running"

        r_stop = api_client.post("/api/simulation/stop")
        assert r_stop.status_code == 200
        assert r_stop.json()["status"] == "stopped"
        assert r_stop.json()["id"] == run["id"]

    def test_pause_without_any_session_returns_404(self, api_client, db_session):
        r = api_client.post("/api/simulation/pause")
        assert r.status_code == 404

    def test_resume_while_running_returns_409(self, api_client, db_session):
        api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        r = api_client.post("/api/simulation/resume")
        assert r.status_code == 409

    def test_step_while_running_returns_409(self, api_client, db_session):
        api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        r = api_client.post("/api/simulation/step")
        assert r.status_code == 409

    def test_events_are_recorded_for_each_transition(self, api_client, db_session):
        from sqlalchemy import select

        from app.db.models import LiveEvent

        api_client.post("/api/simulation/start", json={"mode": "hybrid"})
        api_client.post("/api/simulation/pause")
        api_client.post("/api/simulation/step")
        api_client.post("/api/simulation/resume")
        api_client.post("/api/simulation/stop")

        types = [
            row.event_type for row in db_session.execute(select(LiveEvent).order_by(LiveEvent.id)).scalars().all()
        ]
        assert types == [
            "simulation_started",
            "simulation_paused",
            "manual_step",
            "simulation_resumed",
            "simulation_stopped",
        ]
