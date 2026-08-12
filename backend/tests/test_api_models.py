"""``api/routers/models.py`` testleri — TASARIM.md §4, §12.7. Salt okunur:
hiçbir POST/PUT/DELETE YOKTUR (aktifleştirme ``scripts/activate_model.py``
ile elle yapılır)."""

from __future__ import annotations

import datetime as dt

from app.db import crud

_REWARD_WEIGHTS = {"omega1": 1.0, "omega2": 0.2, "r_s": 20.0, "beta0": 2.0, "beta1": 0.5, "beta2": 1.0}


def _register(db_session, *, level: str, name: str, active: bool) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    model_id = crud.record_model_version(
        db_session, level=level, name=name, checkpoint_path=f"model_registry/{name}.pt",
        trained_at=now, training_run_id=None, hyperparams={"reward_weights": _REWARD_WEIGHTS}, metrics={},
    )
    if active:
        crud.activate_model_version(db_session, model_version_id=model_id)
    return model_id


class TestListModels:
    def test_filters_by_level(self, api_client, db_session):
        _register(db_session, level="manager", name="m1", active=False)
        _register(db_session, level="worker", name="w1", active=False)

        r = api_client.get("/api/models", params={"level": "manager"})
        assert r.status_code == 200
        body = r.json()
        assert body
        assert all(row["level"] == "manager" for row in body)

    def test_filters_by_is_active(self, api_client, db_session):
        active_id = _register(db_session, level="manager", name="m-active", active=True)
        _register(db_session, level="manager", name="m-inactive", active=False)

        r = api_client.get("/api/models", params={"level": "manager", "is_active": True})
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == active_id


class TestActiveModels:
    def test_no_active_models_returns_nulls(self, api_client, db_session):
        from sqlalchemy import update

        from app.db.models import ModelVersion

        db_session.execute(update(ModelVersion).values(is_active=False))
        db_session.flush()

        r = api_client.get("/api/models/active")
        assert r.status_code == 200
        body = r.json()
        assert body["manager"] is None
        assert body["worker"] is None

    def test_returns_the_active_pair(self, api_client, db_session):
        from sqlalchemy import update

        from app.db.models import ModelVersion

        db_session.execute(update(ModelVersion).values(is_active=False))
        manager_id = _register(db_session, level="manager", name="m2", active=True)
        worker_id = _register(db_session, level="worker", name="w2", active=True)

        r = api_client.get("/api/models/active")
        body = r.json()
        assert body["manager"]["id"] == manager_id
        assert body["worker"]["id"] == worker_id
        assert body["manager"]["hyperparams"]["reward_weights"] == _REWARD_WEIGHTS
