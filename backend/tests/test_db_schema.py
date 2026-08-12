"""Faz 1 cikis kriteri testleri: 11 tablo + 1 view dogru kuruldu mu,
FK/CHECK/UNIQUE kisitlari calisiyor mu, constraint_config dogru seed edildi mi.
"""

import datetime as dt

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    ConstraintConfig,
    CourseSlot,
    LiveEvent,
    ManagerDecision,
    MainProductGroup,
    ModelVersion,
    RollingCourse,
    SimulationRun,
    SlabOrder,
    TrainingRun,
    WorkerDecision,
)

EXPECTED_TABLES = {
    "slab_orders",
    "main_product_groups",
    "rolling_courses",
    "course_slots",
    "manager_decisions",
    "worker_decisions",
    "live_events",
    "simulation_runs",
    "model_versions",
    "training_runs",
    "constraint_config",
}


def test_all_11_tables_exist(db_session):
    inspector = inspect(db_session.bind)
    table_names = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - table_names
    assert not missing, f"Eksik tablolar: {missing}"


def test_v_active_course_state_view_exists(db_session):
    inspector = inspect(db_session.bind)
    view_names = set(inspector.get_view_names())
    assert "v_active_course_state" in view_names


def test_constraint_config_seeded_with_expected_keys(db_session):
    rows = db_session.query(ConstraintConfig).all()
    keys = {row.key for row in rows}
    assert keys == {
        "delta_w",
        "delta_t",
        "delta_h",
        "delta_theta",
        "Kz",
        "Lr",
        "m_min",
        "m_max",
        "soft_transition_limit",
    }
    soft_limit = db_session.query(ConstraintConfig).filter_by(key="soft_transition_limit").one()
    assert float(soft_limit.value) == 3.0


def test_circular_fk_slab_orders_main_product_groups(db_session):
    """slab_orders.main_group_id <-> main_product_groups.first/last_order_id cember bagimliligi."""
    first = SlabOrder(order_class="main", source="synthetic", status="pending")
    last = SlabOrder(order_class="main", source="synthetic", status="pending")
    db_session.add_all([first, last])
    db_session.flush()

    group = MainProductGroup(
        steel_grade="Q235",
        first_order_id=first.id,
        last_order_id=last.id,
        group_size=2,
        initial_group_size=2,
        status="available",
    )
    db_session.add(group)
    db_session.flush()

    first.main_group_id = group.id
    db_session.flush()

    db_session.refresh(first)
    assert first.main_group_id == group.id


def test_check_constraint_rejects_invalid_status(db_session):
    bad = SlabOrder(order_class="main", source="synthetic", status="not_a_real_status")
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_check_constraint_rejects_invalid_order_class(db_session):
    bad = SlabOrder(order_class="invalid_class", source="synthetic")
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_unique_constraint_course_slots_position(db_session):
    course = RollingCourse(course_number=999901, min_orders=60, max_orders=100)
    db_session.add(course)
    db_session.flush()

    slot1 = CourseSlot(course_id=course.id, position_index=1, role="main")
    db_session.add(slot1)
    db_session.flush()

    slot2 = CourseSlot(course_id=course.id, position_index=1, role="main")
    db_session.add(slot2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_rolling_course_number_unique(db_session):
    db_session.add(RollingCourse(course_number=999902))
    db_session.flush()
    db_session.add(RollingCourse(course_number=999902))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_v_active_course_state_reflects_active_course_slots(db_session):
    course = RollingCourse(course_number=999903, status="active", min_orders=60, max_orders=100)
    db_session.add(course)
    db_session.flush()

    order = SlabOrder(order_class="main", source="synthetic", status="scheduled")
    db_session.add(order)
    db_session.flush()

    slot = CourseSlot(
        course_id=course.id,
        position_index=1,
        slab_order_id=order.id,
        role="main",
        width_mm=1200.5,
        is_reverse_width=False,
    )
    db_session.add(slot)
    db_session.flush()

    rows = db_session.execute(
        text("SELECT * FROM v_active_course_state WHERE course_id = :cid"),
        {"cid": course.id},
    ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["position_index"] == 1
    assert rows[0]["role"] == "main"
    assert float(rows[0]["width_mm"]) == 1200.5


def test_manager_and_worker_decision_jsonb_roundtrip(db_session):
    course = RollingCourse(course_number=999904)
    db_session.add(course)
    db_session.flush()

    model_version = ModelVersion(level="manager", name="test-manager-v0", is_active=False)
    db_session.add(model_version)
    db_session.flush()

    decision = ManagerDecision(
        course_id=course.id,
        step_index=0,
        state_snapshot={"N": [1, 2, 3], "H_N": 1},
        action_mask={"available_group_ids": [1, 2, 3]},
        reward=0.75,
        model_version_id=model_version.id,
    )
    db_session.add(decision)
    db_session.flush()

    db_session.refresh(decision)
    assert decision.state_snapshot["N"] == [1, 2, 3]
    assert decision.action_mask["available_group_ids"] == [1, 2, 3]

    worker_decision = WorkerDecision(
        manager_decision_id=decision.id,
        course_id=course.id,
        step_index=0,
        state_snapshot={"M": []},
        action_mask={"available_transition_ids": []},
        success=True,
        reward=1.0,
    )
    db_session.add(worker_decision)
    db_session.flush()
    assert worker_decision.id is not None


def test_training_run_and_model_version_relationship(db_session):
    run = TrainingRun(
        started_at=dt.datetime.now(dt.timezone.utc),
        seed=7,
        episodes=100,
        hyperparams={"lr": 0.001},
    )
    db_session.add(run)
    db_session.flush()

    mv = ModelVersion(
        level="worker",
        name="test-worker-v0",
        checkpoint_path="model_registry/worker_test.pt",
        training_run_id=run.id,
        hyperparams={"K_max": 4, "P_max": 8},
        is_active=True,
    )
    db_session.add(mv)
    db_session.flush()
    assert mv.training_run_id == run.id


def test_live_event_check_constraint(db_session):
    db_session.add(LiveEvent(event_type="course_started", payload={"course_number": 1}))
    db_session.flush()

    bad = LiveEvent(event_type="not_a_real_event_type", payload={})
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_simulation_run_mode_and_status_check(db_session):
    run = SimulationRun(mode="hybrid", status="running", tick_interval_ms=1000, config={"seed": 1})
    db_session.add(run)
    db_session.flush()
    assert run.id is not None
