"""``run_loop`` + ``control.py`` uçtan uca (gerçek commit + gerçek NOTIFY)
entegrasyon testi — TASARIM.md §7, §12.6.

Bu dosya gerçek commit'ler kullanır (``run_loop``/``control`` üretim
kodunun ta kendisiyle, ``db_session`` savepoint fixture'ı DEVRE DIŞI
bırakılarak) çünkü otonom tick döngüsü + pause/manual-step davranışı yalnızca
GERÇEK NOTIFY teslimiyle anlamlıdır. Test, oluşturduğu TÜM satırları (id
sınır/boundary tabanlı, bkz. ``_Boundary``) sonunda siler — geliştirme
veritabanındaki gerçek eğitim/demo verisine (ör. aktif model_versions
id=89/90) dokunmaz.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import random

from sqlalchemy import delete, func, select, update

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.base import SessionLocal
from app.db.models import (
    CourseSlot,
    LiveEvent,
    MainProductGroup,
    ManagerDecision,
    ModelVersion,
    RollingCourse,
    SimulationRun,
    SlabOrder,
    WorkerDecision,
)
from app.simulation import control, inference
from app.simulation.live_engine import LiveEngine, LoopBounds, run_loop, watch_and_run
from app.simulation.notifier import LiveEventNotifier
from app.training.agents.dqn_agent import DQNHyperparams
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent

REWARD_WEIGHTS = {"omega1": 1.0, "omega2": 0.2, "r_s": 20.0, "beta0": 2.0, "beta1": 0.5, "beta2": 1.0}
# Silme sırası ÇOCUKTAN EBEVEYNE doğru olmalı (FK ihlallerinden kaçınmak
# için): live_events.course_id -> rolling_courses, bu yüzden LiveEvent
# RollingCourse'dan ÖNCE silinmeli (bkz. bir regresyon testiyle yakalandı).
_BOUNDARY_MODELS = (WorkerDecision, ManagerDecision, CourseSlot, LiveEvent, RollingCourse, SimulationRun)


def _constraints() -> RollingConstraints:
    return RollingConstraints(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=10, m_max=100, soft_transition_limit=3,
    )


def _snapshot_boundaries(session) -> dict:
    boundaries = {m: session.execute(select(func.coalesce(func.max(m.id), 0))).scalar_one() for m in _BOUNDARY_MODELS}
    boundaries[SlabOrder] = session.execute(select(func.coalesce(func.max(SlabOrder.id), 0))).scalar_one()
    boundaries[MainProductGroup] = session.execute(
        select(func.coalesce(func.max(MainProductGroup.id), 0))
    ).scalar_one()
    boundaries[ModelVersion] = session.execute(select(func.coalesce(func.max(ModelVersion.id), 0))).scalar_one()
    return boundaries


def _snapshot_previously_active_models(session) -> dict[str, int | None]:
    """``crud.activate_model_version`` (bu testin ``_setup_active_models``'ı
    tarafından çağrılır) o SEVİYEdeki TÜM diğer satırları pasifleştirir —
    bu GERÇEK bir commit'tir, geliştirme veritabanındaki üretim modellerini
    (ör. id=89/90) de etkiler. Bu yüzden test başlamadan önce "kim aktifti"
    kaydedilir, teardown'da GERİ YÜKLENİR (bkz. ``_cleanup_above``) —
    aksi halde test, üretim/demo sisteminin aktif modelini kalıcı olarak
    değiştirmiş olurdu (bir hata olarak yakalanıp düzeltildi, bkz. §12.6)."""
    return {
        level: (row.id if row is not None else None)
        for level in ("manager", "worker")
        for row in [crud.get_active_model_version(session, level=level)]
    }


def _cleanup_above(boundaries: dict, previously_active: dict[str, int | None]) -> None:
    with SessionLocal() as session:
        session.execute(
            update(SlabOrder).where(SlabOrder.id > boundaries[SlabOrder]).values(main_group_id=None)
        )
        for model in _BOUNDARY_MODELS:
            session.execute(delete(model).where(model.id > boundaries[model]))
        # main_product_groups.first_order_id/last_order_id -> slab_orders.id
        # (dairesel FK, bkz. crud.clear_pending_pool): gruplar order'lardan
        # ÖNCE silinmeli.
        session.execute(delete(MainProductGroup).where(MainProductGroup.id > boundaries[MainProductGroup]))
        session.execute(delete(SlabOrder).where(SlabOrder.id > boundaries[SlabOrder]))
        session.execute(delete(ModelVersion).where(ModelVersion.id > boundaries[ModelVersion]))
        for previous_id in previously_active.values():
            if previous_id is not None:
                crud.activate_model_version(session, model_version_id=previous_id)
        session.commit()


def _setup_active_models(session, tmp_path) -> None:
    hp = DQNHyperparams(hidden_dim=16, epsilon_start=0.0, epsilon_end=0.0)
    manager_agent = build_manager_agent(k_max=4, hyperparams=hp, seed=1)
    worker_agent = build_worker_agent(k_max=4, p_max=30, hyperparams=hp, seed=1)
    manager_path = tmp_path / "manager.pt"
    worker_path = tmp_path / "worker.pt"
    manager_agent.save_checkpoint(manager_path)
    worker_agent.save_checkpoint(worker_path)

    now = dt.datetime.now(dt.timezone.utc)
    manager_id = crud.record_model_version(
        session, level="manager", name="e2e-manager", checkpoint_path=str(manager_path),
        trained_at=now, training_run_id=None, hyperparams={"reward_weights": REWARD_WEIGHTS}, metrics={},
    )
    worker_id = crud.record_model_version(
        session, level="worker", name="e2e-worker", checkpoint_path=str(worker_path),
        trained_at=now, training_run_id=None, hyperparams={"reward_weights": REWARD_WEIGHTS}, metrics={},
    )
    crud.activate_model_version(session, model_version_id=manager_id)
    crud.activate_model_version(session, model_version_id=worker_id)
    session.commit()


def _seed_pool(session, constraints: RollingConstraints, *, seed: int, batches: int) -> None:
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    rng = random.Random(seed)
    for _ in range(batches):
        batch = generate_batch(config, constraints, rng)
        crud.insert_generated_batch(session, batch)
    session.commit()


def _decision_count(session) -> int:
    m = session.execute(select(func.count()).select_from(ManagerDecision)).scalar_one()
    w = session.execute(select(func.count()).select_from(WorkerDecision)).scalar_one()
    return m + w


def test_autonomous_loop_then_pause_manual_step_stop(tmp_path):
    # pytest-timeout kurulu değil; wall-clock sınırları test gövdesi
    # içindeki deadline'larla (asyncio.wait_for / manuel deadline) sağlanır.
    async def _run() -> None:
        constraints = _constraints()
        with SessionLocal() as session:
            boundaries = _snapshot_boundaries(session)
            previously_active = _snapshot_previously_active_models(session)

        try:
            with SessionLocal() as session:
                _setup_active_models(session, tmp_path)
                # batches=5: ilk kurs (m_max=100) kapasitesi dolduğunda bile
                # havuzda manuel adım için bolca ana grup/geçiş order'ı
                # kalmalı -- aksi halde "manuel adım tam olarak bir yeni
                # karar üretir" iddiası havuz tükendiğinde (idle) yanlışlıkla
                # bozulur (bir flaky-test denemesiyle yakalandı, bkz. §12.6).
                _seed_pool(session, constraints, seed=71, batches=5)
                models = inference.load_active_models(session)
                run = control.start(
                    session, mode="hybrid", tick_interval_ms=5,
                    manager_model_version_id=models.manager_model_version_id,
                    worker_model_version_id=models.worker_model_version_id,
                    config={"e2e": True},
                )
                session.commit()
                run_id = run.id

            bounds = LoopBounds(max_manager_steps_per_course=20, max_worker_steps_per_subtask=10)
            engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)

            async with LiveEventNotifier() as notifier:
                task = asyncio.create_task(run_loop(engine=engine, run_id=run_id, notifier=notifier))
                try:
                    # 1) otonom modda en az bir kursun tamamen kapanmasını bekle.
                    deadline = asyncio.get_event_loop().time() + 15.0
                    closed = False
                    while asyncio.get_event_loop().time() < deadline:
                        with SessionLocal() as session:
                            n = session.execute(
                                select(func.count())
                                .select_from(LiveEvent)
                                .where(LiveEvent.event_type.in_(["course_completed", "course_failed"]))
                            ).scalar_one()
                        if n > 0:
                            closed = True
                            break
                        await asyncio.sleep(0.2)
                    assert closed, "15sn içinde otonom modda hiçbir kurs kapanmadı"

                    # 2) pause -- döngü kısa sürede status'ü yeniden okuyup duraklamalı.
                    with SessionLocal() as session:
                        control.pause(session, run_id)
                        session.commit()
                    await asyncio.sleep(0.5)
                    with SessionLocal() as session:
                        assert crud.get_simulation_run(session, run_id).status == "paused"
                        before = _decision_count(session)

                    # 3) PAUSED iken sistem kendiliğinden karar ÜRETMEMELİ.
                    await asyncio.sleep(0.5)
                    with SessionLocal() as session:
                        assert _decision_count(session) == before

                    # 4) manuel adım TAM OLARAK bir yeni karar üretmeli.
                    with SessionLocal() as session:
                        control.request_step(session, run_id)
                        session.commit()
                    await asyncio.sleep(1.0)
                    with SessionLocal() as session:
                        after = _decision_count(session)
                        assert crud.get_simulation_run(session, run_id).status == "paused"
                    assert after == before + 1
                finally:
                    with SessionLocal() as session:
                        control.stop(session, run_id)
                        session.commit()
                    await asyncio.wait_for(task, timeout=5.0)
        finally:
            _cleanup_above(boundaries, previously_active)

    asyncio.run(_run())


def test_watch_and_run_picks_up_externally_created_sessions(tmp_path):
    """Faz 6 entegrasyonu: ``watch_and_run`` kendi oturumunu AÇMAZ, DB'de
    (ör. ``POST /api/simulation/start`` ile) BAŞKASI TARAFINDAN oluşturulan
    bir sonraki durdurulmamış oturumu yakalayıp sürer; o oturum durunca bir
    SONRAKİ (yine dışarıdan açılan) oturumu da aynı şekilde yakalar — motor
    süreci kimin/neyin oturum açtığına bakmaksızın sürekli ayakta kalır
    (TASARIM.md §2, §12.7)."""

    async def _run() -> None:
        constraints = _constraints()
        with SessionLocal() as session:
            boundaries = _snapshot_boundaries(session)
            previously_active = _snapshot_previously_active_models(session)

        try:
            with SessionLocal() as session:
                _setup_active_models(session, tmp_path)
                _seed_pool(session, constraints, seed=91, batches=5)
                models = inference.load_active_models(session)

            bounds = LoopBounds(max_manager_steps_per_course=20, max_worker_steps_per_subtask=10)
            watch_task = asyncio.create_task(watch_and_run(models=models, constraints=constraints, bounds=bounds))
            try:
                # 1) "API" (burada doğrudan control.start ile simüle edildi)
                # bir oturum açar -- watch_and_run BUNU AÇMADIĞI HALDE
                # yakalayıp sürmeli.
                with SessionLocal() as session:
                    run1 = control.start(
                        session, mode="hybrid", tick_interval_ms=5,
                        manager_model_version_id=models.manager_model_version_id,
                        worker_model_version_id=models.worker_model_version_id,
                        config={"source": "external-1"},
                    )
                    session.commit()

                deadline = asyncio.get_event_loop().time() + 15.0
                closed = False
                while asyncio.get_event_loop().time() < deadline:
                    with SessionLocal() as session:
                        n = session.execute(
                            select(func.count())
                            .select_from(LiveEvent)
                            .where(LiveEvent.event_type.in_(["course_completed", "course_failed"]))
                        ).scalar_one()
                    if n > 0:
                        closed = True
                        break
                    await asyncio.sleep(0.2)
                assert closed, "watch_and_run 15sn içinde dışarıdan açılan İLK oturumu sürmedi"

                with SessionLocal() as session:
                    control.stop(session, run1.id)
                    session.commit()
                await asyncio.sleep(0.3)

                # 2) İKİNCİ, yine dışarıdan açılan bir oturum -- watch_and_run
                # kendi while True döngüsünde bir SONRAKİ oturuma geçmeli.
                with SessionLocal() as session:
                    decisions_before = _decision_count(session)
                    run2 = control.start(
                        session, mode="hybrid", tick_interval_ms=5,
                        manager_model_version_id=models.manager_model_version_id,
                        worker_model_version_id=models.worker_model_version_id,
                        config={"source": "external-2"},
                    )
                    session.commit()

                deadline2 = asyncio.get_event_loop().time() + 15.0
                progressed = False
                while asyncio.get_event_loop().time() < deadline2:
                    with SessionLocal() as session:
                        if _decision_count(session) > decisions_before:
                            progressed = True
                            break
                    await asyncio.sleep(0.2)
                assert progressed, "watch_and_run 15sn içinde dışarıdan açılan İKİNCİ oturuma geçmedi"

                with SessionLocal() as session:
                    control.stop(session, run2.id)
                    session.commit()
            finally:
                watch_task.cancel()
                try:
                    await watch_task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            _cleanup_above(boundaries, previously_active)

    asyncio.run(_run())
