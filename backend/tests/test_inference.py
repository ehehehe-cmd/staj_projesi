"""simulation/inference.py birim testleri — TASARIM.md §7, §12.6."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import update

from app.db import crud
from app.db.models import ModelVersion
from app.simulation import inference
from app.training.agents.dqn_agent import DQNHyperparams
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent

_REWARD_WEIGHTS = {"omega1": 1.0, "omega2": 0.2, "r_s": 20.0, "beta0": 2.0, "beta1": 0.5, "beta2": 1.0}


def _tiny_hp() -> DQNHyperparams:
    return DQNHyperparams(hidden_dim=8)


def _deactivate_all_model_versions(db_session) -> None:
    """Geliştirme veritabanında zaten aktif işaretli gerçek modeller (ör.
    id=89/90) olabilir; "aktif model yok" senaryosunu test edebilmek için
    bunları BU TEST TRANSACTION'I İÇİNDE (rollback ile geri alınacak
    şekilde) geçici olarak pasifleştiriyoruz."""
    db_session.execute(update(ModelVersion).values(is_active=False))
    db_session.flush()


def _save_tiny_checkpoints(tmp_path, *, k_max: int = 4, p_max: int = 10, seed: int = 1):
    hp = _tiny_hp()
    manager_agent = build_manager_agent(k_max=k_max, hyperparams=hp, seed=seed)
    worker_agent = build_worker_agent(k_max=k_max, p_max=p_max, hyperparams=hp, seed=seed)
    manager_path = tmp_path / "manager.pt"
    worker_path = tmp_path / "worker.pt"
    manager_agent.save_checkpoint(manager_path)
    worker_agent.save_checkpoint(worker_path)
    return manager_path, worker_path


def _register(db_session, *, manager_path, worker_path, hyperparams: dict) -> tuple[int, int]:
    now = dt.datetime.now(dt.timezone.utc)
    manager_id = crud.record_model_version(
        db_session, level="manager", name="test-manager", checkpoint_path=str(manager_path),
        trained_at=now, training_run_id=None, hyperparams=hyperparams, metrics={},
    )
    worker_id = crud.record_model_version(
        db_session, level="worker", name="test-worker", checkpoint_path=str(worker_path),
        trained_at=now, training_run_id=None, hyperparams=hyperparams, metrics={},
    )
    crud.activate_model_version(db_session, model_version_id=manager_id)
    crud.activate_model_version(db_session, model_version_id=worker_id)
    db_session.flush()
    return manager_id, worker_id


class TestLoadActiveModels:
    def test_raises_when_no_active_manager(self, db_session):
        _deactivate_all_model_versions(db_session)
        with pytest.raises(inference.NoActiveModelError):
            inference.load_active_models(db_session)

    def test_raises_when_reward_weights_missing(self, db_session, tmp_path):
        _deactivate_all_model_versions(db_session)
        manager_path, worker_path = _save_tiny_checkpoints(tmp_path)
        _register(db_session, manager_path=manager_path, worker_path=worker_path, hyperparams={})
        with pytest.raises(inference.NoActiveModelError):
            inference.load_active_models(db_session)

    def test_raises_when_worker_missing_even_if_manager_active(self, db_session, tmp_path):
        _deactivate_all_model_versions(db_session)
        hp = _tiny_hp()
        manager_agent = build_manager_agent(k_max=4, hyperparams=hp, seed=1)
        manager_path = tmp_path / "manager.pt"
        manager_agent.save_checkpoint(manager_path)
        now = dt.datetime.now(dt.timezone.utc)
        manager_id = crud.record_model_version(
            db_session, level="manager", name="m", checkpoint_path=str(manager_path),
            trained_at=now, training_run_id=None, hyperparams={"reward_weights": _REWARD_WEIGHTS}, metrics={},
        )
        crud.activate_model_version(db_session, model_version_id=manager_id)
        with pytest.raises(inference.NoActiveModelError):
            inference.load_active_models(db_session)

    def test_loads_active_manager_and_worker(self, db_session, tmp_path):
        manager_path, worker_path = _save_tiny_checkpoints(tmp_path, k_max=4, p_max=10)
        manager_id, worker_id = _register(
            db_session, manager_path=manager_path, worker_path=worker_path,
            hyperparams={"reward_weights": _REWARD_WEIGHTS},
        )

        models = inference.load_active_models(db_session)

        assert models.manager_model_version_id == manager_id
        assert models.worker_model_version_id == worker_id
        assert models.k_max == 4
        assert models.p_max == 10
        assert models.reward_weights == _REWARD_WEIGHTS

    def test_picks_up_newly_activated_model_after_hot_swap(self, db_session, tmp_path):
        manager_path1, worker_path1 = _save_tiny_checkpoints(tmp_path, seed=1)
        id1_m, id1_w = _register(
            db_session, manager_path=manager_path1, worker_path=worker_path1,
            hyperparams={"reward_weights": _REWARD_WEIGHTS},
        )
        models_before = inference.load_active_models(db_session)
        assert models_before.manager_model_version_id == id1_m

        manager_path2, worker_path2 = _save_tiny_checkpoints(tmp_path / "v2", seed=2)
        id2_m, id2_w = _register(
            db_session, manager_path=manager_path2, worker_path=worker_path2,
            hyperparams={"reward_weights": _REWARD_WEIGHTS},
        )
        models_after = inference.load_active_models(db_session)
        assert models_after.manager_model_version_id == id2_m
        assert models_after.manager_model_version_id != id1_m
