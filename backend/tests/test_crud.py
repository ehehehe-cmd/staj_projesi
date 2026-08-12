"""db/crud.py birim testleri — Faz 3 (gerçek Postgres'e karşı, savepoint izolasyonlu).

Faz 4: record_training_run/record_model_version/activate_model_version testleri eklendi.
"""

import datetime as dt
import random

from sqlalchemy import select

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.models import MainProductGroup, ModelVersion, SlabOrder, TrainingRun


def test_load_constraint_config_returns_9_keys(db_session):
    constraints = crud.load_constraint_config(db_session)
    assert isinstance(constraints, RollingConstraints)
    # Faz 3 Kz recalibration migration'ının uygulandığını da doğrular.
    assert constraints.kz == 3_000_000.0
    assert constraints.soft_transition_limit == 3


def test_clear_pending_pool_removes_only_pending_orders(db_session):
    kept = SlabOrder(
        steel_grade="X",
        width_mm=1000,
        thickness_mm=2,
        hardness=50,
        heating_temp_c=850,
        slab_width_mm=1000,
        slab_thickness_mm=200,
        slab_length_mm=8000,
        order_class="main",
        status="scheduled",
        source="synthetic",
    )
    pending = SlabOrder(
        steel_grade="X",
        width_mm=1000,
        thickness_mm=2,
        hardness=50,
        heating_temp_c=850,
        slab_width_mm=1000,
        slab_thickness_mm=200,
        slab_length_mm=8000,
        order_class="main",
        status="pending",
        source="synthetic",
    )
    db_session.add_all([kept, pending])
    db_session.flush()

    deleted_orders, deleted_groups = crud.clear_pending_pool(db_session)
    assert deleted_orders == 1
    assert deleted_groups == 0

    remaining = db_session.execute(select(SlabOrder.id).where(SlabOrder.status == "scheduled")).scalars().all()
    assert kept.id in remaining


def test_clear_pending_pool_breaks_circular_fk_before_deleting(db_session):
    first = SlabOrder(
        steel_grade="X", width_mm=1000, thickness_mm=2, hardness=50, heating_temp_c=850,
        slab_width_mm=1000, slab_thickness_mm=200, slab_length_mm=8000,
        order_class="main", status="pending", source="synthetic",
    )
    last = SlabOrder(
        steel_grade="X", width_mm=1000, thickness_mm=2, hardness=51, heating_temp_c=851,
        slab_width_mm=1000, slab_thickness_mm=200, slab_length_mm=8000,
        order_class="main", status="pending", source="synthetic",
    )
    db_session.add_all([first, last])
    db_session.flush()

    group = MainProductGroup(
        steel_grade="X", first_order_id=first.id, last_order_id=last.id,
        group_size=2, initial_group_size=2, status="available",
    )
    db_session.add(group)
    db_session.flush()
    first.main_group_id = group.id
    last.main_group_id = group.id
    db_session.flush()

    # Bu çağrı, dairesel FK yüzünden IntegrityError fırlatmamalı (bkz. crud.py docstring).
    deleted_orders, deleted_groups = crud.clear_pending_pool(db_session)
    assert deleted_orders == 2
    assert deleted_groups == 1


def test_insert_generated_batch_round_trip(db_session):
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    constraints = RollingConstraints(
        delta_w=50.0, delta_t=0.5, delta_h=5.0, delta_theta=30.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    batch = generate_batch(config, constraints, random.Random(7))

    inserted = crud.insert_generated_batch(db_session, batch)
    assert inserted == len(batch.orders)

    db_session.flush()
    db_orders = db_session.execute(select(SlabOrder).where(SlabOrder.source == "synthetic")).scalars().all()
    assert len(db_orders) == len(batch.orders)

    db_groups = db_session.execute(select(MainProductGroup)).scalars().all()
    assert len(db_groups) == len(batch.main_groups)

    for db_group in db_groups:
        first_order = db_session.get(SlabOrder, db_group.first_order_id)
        last_order = db_session.get(SlabOrder, db_group.last_order_id)
        assert first_order is not None and last_order is not None
        assert first_order.main_group_id == db_group.id
        assert last_order.main_group_id == db_group.id

    main_orders = [o for o in db_orders if o.order_class == "main"]
    transition_orders = [o for o in db_orders if o.order_class == "transition"]
    assert all(o.main_group_id is not None for o in main_orders)
    assert all(o.main_group_id is None for o in transition_orders)
    assert all(o.theoretical_rolling_length is not None and o.theoretical_rolling_length > 0 for o in db_orders)


def test_record_training_run_and_model_version_round_trip(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    run_id = crud.record_training_run(
        db_session,
        started_at=now,
        ended_at=now,
        seed=7,
        episodes=10,
        hyperparams={"learning_rate": 0.001},
        notes="test run",
    )
    db_session.flush()
    row = db_session.get(TrainingRun, run_id)
    assert row is not None
    assert row.seed == 7
    assert row.hyperparams == {"learning_rate": 0.001}

    version_id = crud.record_model_version(
        db_session,
        level="manager",
        name="manager_test",
        checkpoint_path="model_registry/manager_test.pt",
        trained_at=now,
        training_run_id=run_id,
        hyperparams={"k_max": 10},
        metrics={"tail_avg_manager_reward": 0.9},
    )
    db_session.flush()
    mv = db_session.get(ModelVersion, version_id)
    assert mv is not None
    assert mv.is_active is False
    assert mv.training_run_id == run_id
    assert mv.hyperparams == {"k_max": 10}


def test_activate_model_version_deactivates_same_level_siblings(db_session):
    now = dt.datetime.now(dt.timezone.utc)
    run_id = crud.record_training_run(
        db_session, started_at=now, ended_at=now, seed=1, episodes=1, hyperparams={}, notes=""
    )
    v1 = crud.record_model_version(
        db_session, level="manager", name="m1", checkpoint_path="p1", trained_at=now,
        training_run_id=run_id, hyperparams={}, metrics={},
    )
    v2 = crud.record_model_version(
        db_session, level="manager", name="m2", checkpoint_path="p2", trained_at=now,
        training_run_id=run_id, hyperparams={}, metrics={},
    )
    other_level = crud.record_model_version(
        db_session, level="worker", name="w1", checkpoint_path="p3", trained_at=now,
        training_run_id=run_id, hyperparams={}, metrics={},
    )
    db_session.flush()

    crud.activate_model_version(db_session, model_version_id=v1)
    db_session.flush()
    assert db_session.get(ModelVersion, v1).is_active is True

    crud.activate_model_version(db_session, model_version_id=v2)
    db_session.flush()
    assert db_session.get(ModelVersion, v1).is_active is False
    assert db_session.get(ModelVersion, v2).is_active is True
    # farklı seviyedeki (worker) kayıt etkilenmemeli
    assert db_session.get(ModelVersion, other_level).is_active is False
