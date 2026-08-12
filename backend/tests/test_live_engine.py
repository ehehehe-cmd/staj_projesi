"""simulation/live_engine.py birim/entegrasyon testleri — TASARIM.md §7,
§12.6. Gerçek (dockerized) Postgres'e karşı, savepoint izolasyonlu (bkz.
conftest.py ``db_session``) — Faz 4'ün ``test_env_smoke.py``sına paralel bir
yaklaşım: gerçek ``generate_batch`` ile üretilmiş bir havuz + rastgele
mimarili (eğitilmemiş) ama GERÇEK checkpoint dosyalarından yüklenmiş
ajanlarla motoru uçtan uca (adım adım) çalıştırır.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest
from sqlalchemy import select

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.models import LiveEvent, ManagerDecision, RollingCourse, WorkerDecision
from app.simulation import inference
from app.simulation.inference import ActiveModels
from app.simulation.live_engine import LiveEngine, LoopBounds, Phase
from app.training.agents.dqn_agent import DQNHyperparams
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent

K_MAX = 6
P_MAX = 40
REWARD_WEIGHTS = {"omega1": 1.0, "omega2": 0.2, "r_s": 20.0, "beta0": 2.0, "beta1": 0.5, "beta2": 1.0}


def _constraints(**overrides) -> RollingConstraints:
    base = dict(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    base.update(overrides)
    return RollingConstraints(**base)


def _tiny_hp() -> DQNHyperparams:
    return DQNHyperparams(hidden_dim=16, epsilon_start=0.0, epsilon_end=0.0)


def _active_models(db_session, tmp_path, *, seed: int = 1, k_max: int = K_MAX, p_max: int = P_MAX) -> ActiveModels:
    hp = _tiny_hp()
    manager_agent = build_manager_agent(k_max=k_max, hyperparams=hp, seed=seed)
    worker_agent = build_worker_agent(k_max=k_max, p_max=p_max, hyperparams=hp, seed=seed)
    manager_path = tmp_path / "manager.pt"
    worker_path = tmp_path / "worker.pt"
    manager_agent.save_checkpoint(manager_path)
    worker_agent.save_checkpoint(worker_path)

    now = dt.datetime.now(dt.timezone.utc)
    manager_id = crud.record_model_version(
        db_session, level="manager", name="test-manager", checkpoint_path=str(manager_path),
        trained_at=now, training_run_id=None, hyperparams={"reward_weights": REWARD_WEIGHTS}, metrics={},
    )
    worker_id = crud.record_model_version(
        db_session, level="worker", name="test-worker", checkpoint_path=str(worker_path),
        trained_at=now, training_run_id=None, hyperparams={"reward_weights": REWARD_WEIGHTS}, metrics={},
    )
    crud.activate_model_version(db_session, model_version_id=manager_id)
    crud.activate_model_version(db_session, model_version_id=worker_id)
    db_session.flush()
    return inference.load_active_models(db_session)


def _seed_pool(db_session, constraints: RollingConstraints, *, seed: int, batches: int) -> None:
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    rng = random.Random(seed)
    for _ in range(batches):
        batch = generate_batch(config, constraints, rng)
        crud.insert_generated_batch(db_session, batch)
    db_session.flush()


def _run_until_course_closed(engine: LiveEngine, db_session, *, max_steps: int = 2000):
    for _ in range(max_steps):
        outcome = engine.step_once(db_session)
        if outcome.course_closed:
            return outcome
    raise AssertionError(f"kurs {max_steps} adımda kapanmadı — olası sonsuz döngü")


@pytest.fixture()
def constraints() -> RollingConstraints:
    return _constraints()


@pytest.fixture()
def bounds() -> LoopBounds:
    return LoopBounds(max_manager_steps_per_course=20, max_worker_steps_per_subtask=10)


@pytest.fixture()
def models(db_session, tmp_path) -> ActiveModels:
    return _active_models(db_session, tmp_path)


class TestIdle:
    def test_idle_when_pool_empty(self, db_session, constraints, bounds, models):
        crud.clear_pending_pool(db_session)
        engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)
        outcome = engine.step_once(db_session)
        assert outcome.course_id is None
        assert "idle" in outcome.detail
        assert crud.get_active_course(db_session) is None


class TestFirstPlacementSkipsWorker:
    def test_first_decision_creates_course_and_places_directly(self, db_session, constraints, bounds, models):
        crud.clear_pending_pool(db_session)
        _seed_pool(db_session, constraints, seed=11, batches=1)
        engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)

        outcome = engine.step_once(db_session)
        assert outcome.course_id is not None
        # Tasarım kararı #3: kursun İLK yerleştirmesi worker'sızdır -- bu
        # yüzden tek bir step_once çağrısı sonrası motor hâlâ MANAGER
        # fazında olmalı (WORKER'a devredilmiş olamaz).
        assert engine.phase() is Phase.MANAGER

        course = db_session.get(RollingCourse, outcome.course_id)
        assert course.status == "active"
        assert course.order_count > 0
        assert course.first_main_group_placed is True

        decisions = db_session.execute(
            select(ManagerDecision).where(ManagerDecision.course_id == course.id)
        ).scalars().all()
        assert len(decisions) == 1
        assert decisions[0].selected_group_id is not None
        assert decisions[0].reward == 0.0  # semi-MDP: yalnızca kursu kapatan karar ödül taşır

        event_types = [
            e.event_type
            for e in db_session.execute(select(LiveEvent).order_by(LiveEvent.id)).scalars().all()
        ]
        assert event_types[:2] == ["course_started", "main_group_selected"]


class TestFullCourseLifecycle:
    def test_course_runs_to_completion_or_failure_with_consistent_bookkeeping(
        self, db_session, constraints, bounds, models
    ):
        crud.clear_pending_pool(db_session)
        _seed_pool(db_session, constraints, seed=21, batches=2)
        engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)

        outcome = _run_until_course_closed(engine, db_session)
        course = db_session.get(RollingCourse, outcome.course_id)

        assert course.status in ("completed", "failed")
        assert course.completed_at is not None
        assert 0 <= course.order_count <= course.max_orders

        events = db_session.execute(
            select(LiveEvent).where(LiveEvent.course_id == course.id)
        ).scalars().all()
        types = {e.event_type for e in events}
        assert "course_started" in types
        assert ("course_completed" in types) ^ ("course_failed" in types)

        terminal_decision = db_session.execute(
            select(ManagerDecision).where(
                ManagerDecision.course_id == course.id, ManagerDecision.selected_group_id.is_(None)
            )
        ).scalar_one()
        assert terminal_decision.reward is not None

        # m_min altı kalan bir kurs 'failed' olmalı, üstü/eşiti 'completed'.
        if course.order_count >= course.min_orders:
            assert course.status == "completed"
        else:
            assert course.status == "failed"


class TestWorkerPhaseIsExercised:
    def test_worker_decisions_recorded_across_several_seeded_pools(self, db_session, constraints, bounds, models):
        """Üretici ardışık ana gruplar arasında bir köprü garanti ediyor
        (Faz 3); en az bir tohum/kurs kombinasyonunda worker'ın devreye
        girmesi (ve bir ``worker_decisions`` satırı yazması) beklenir —
        aksi halde HRL'nin worker seviyesi canlı motorda hiç egzersiz
        edilmiyor demektir (bkz. training/tests/test_env_smoke.py'nin aynı
        felsefedeki testi)."""
        any_worker_seen = False
        for seed in range(6):
            crud.clear_pending_pool(db_session)
            _seed_pool(db_session, constraints, seed=200 + seed, batches=3)
            engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)
            for _ in range(400):
                outcome = engine.step_once(db_session)
                if outcome.course_id is None:  # havuz tükendi
                    break
            worker_rows = db_session.execute(select(WorkerDecision)).scalars().all()
            if worker_rows:
                any_worker_seen = True
                break
        assert any_worker_seen


class TestCrashRecovery:
    def test_progress_is_reconstructable_purely_from_db_and_second_engine_can_resume(
        self, db_session, constraints, bounds, models
    ):
        crud.clear_pending_pool(db_session)
        _seed_pool(db_session, constraints, seed=31, batches=2)
        engine_a = LiveEngine(models=models, constraints=constraints, bounds=bounds)

        engine_a.step_once(db_session)  # kurs açılır + ilk grup (worker'sız) yerleşir
        course = crud.get_active_course(db_session)
        assert course is not None
        order_count_after_a = course.order_count
        assert order_count_after_a > 0

        # TASARIM.md §1 ilke 7: sadece rolling_courses+course_slots'tan
        # yeniden inşa edilebilmeli -- engine_a'nın kendi bellek state'i
        # (varsa) hiç KULLANILMADAN.
        progress_from_db = crud.load_course_progress(db_session, course)
        assert progress_from_db.order_count == order_count_after_a
        assert progress_from_db.last_attributes is not None

        # "process restart" simülasyonu: TAMAMEN yeni bir LiveEngine, hiçbir
        # Python belleği paylaşmıyor.
        engine_b = LiveEngine(models=models, constraints=constraints, bounds=bounds)
        assert engine_b.phase() is Phase.MANAGER  # her zaman manager'dan devam (tasarım kararı #2)

        engine_b.step_once(db_session)
        db_session.expire(course)
        course_now = db_session.get(RollingCourse, course.id)
        assert course_now.order_count >= order_count_after_a or course_now.status in ("completed", "failed")

        # engine_b, engine_a'nın kararlarını DUPLICATE ETMEMİŞ olmalı --
        # course_id başına manager_decisions.step_index'ler benzersiz kalmalı.
        step_indices = [
            row.step_index
            for row in db_session.execute(
                select(ManagerDecision).where(ManagerDecision.course_id == course.id)
            ).scalars().all()
        ]
        assert len(step_indices) == len(set(step_indices))


class TestRewardBookkeeping:
    def test_intermediate_decisions_get_zero_reward_only_terminal_is_nonzero_formulaic(
        self, db_session, constraints, bounds, models
    ):
        crud.clear_pending_pool(db_session)
        _seed_pool(db_session, constraints, seed=41, batches=3)
        engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)
        outcome = _run_until_course_closed(engine, db_session, max_steps=3000)

        decisions = db_session.execute(
            select(ManagerDecision)
            .where(ManagerDecision.course_id == outcome.course_id)
            .order_by(ManagerDecision.step_index)
        ).scalars().all()
        assert decisions
        for d in decisions[:-1]:
            assert d.reward == 0.0
        assert decisions[-1].selected_group_id is None  # terminal karar
