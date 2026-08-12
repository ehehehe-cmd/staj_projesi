"""db/crud.py Faz 5 (canlı simülasyon) yardımcılarının birim testleri —
TASARIM.md §7, §12.6. Gerçek (dockerized) Postgres'e karşı, savepoint
izolasyonlu (bkz. conftest.py ``db_session``)."""

from __future__ import annotations

import random

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.models import MainProductGroup
from app.domain.dto import OrderAttributes


def _constraints(**overrides) -> RollingConstraints:
    base = dict(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    base.update(overrides)
    return RollingConstraints(**base)


def _seed(db_session, *, seed: int, batches: int = 1, constraints: RollingConstraints | None = None) -> None:
    constraints = constraints or _constraints()
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    rng = random.Random(seed)
    for _ in range(batches):
        batch = generate_batch(config, constraints, rng)
        crud.insert_generated_batch(db_session, batch)
    db_session.flush()


class TestCourseLifecycle:
    def test_start_new_course_increments_course_number(self, db_session):
        c = _constraints()
        first = crud.start_new_course(db_session, constraints=c)
        second = crud.start_new_course(db_session, constraints=c)
        assert second.course_number == first.course_number + 1
        assert first.status == "active"
        assert first.max_orders == c.m_max
        assert first.min_orders == c.m_min
        assert first.order_count == 0

    def test_get_active_course_returns_none_when_no_active(self, db_session):
        assert crud.get_active_course(db_session) is None

    def test_get_active_course_finds_the_active_row(self, db_session):
        course = crud.start_new_course(db_session, constraints=_constraints())
        found = crud.get_active_course(db_session)
        assert found is not None
        assert found.id == course.id


class TestCourseProgress:
    def test_load_course_progress_for_empty_course(self, db_session):
        c = _constraints()
        course = crud.start_new_course(db_session, constraints=c)
        progress = crud.load_course_progress(db_session, course)
        assert progress.order_count == 0
        assert progress.max_orders == c.m_max
        assert progress.cumulative_length_mm == 0.0
        assert progress.reverse_width_events_count == 0
        assert progress.last_attributes is None


class TestGroupAndTransitionPools:
    def test_load_available_groups_respects_limit_and_exclude(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=1, batches=3)

        all_groups = crud.load_available_groups(db_session, limit=1000)
        assert len(all_groups) >= 2

        limited = crud.load_available_groups(db_session, limit=1)
        assert len(limited) == 1

        excluded_id = all_groups[0].id
        without_first = crud.load_available_groups(db_session, limit=1000, exclude_ids={excluded_id})
        assert excluded_id not in [g.id for g in without_first]
        assert len(without_first) == len(all_groups) - 1

    def test_load_available_groups_without_last_attributes_is_fifo(self, db_session):
        # TASARIM.md §14.3.E: last_attributes/constraints verilmezse eski FIFO
        # davranışı (id sırası) birebir korunur -- geriye dönük uyumluluk.
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=7, batches=3)
        groups = crud.load_available_groups(db_session, limit=1000)
        assert [g.id for g in groups] == sorted(g.id for g in groups)

    def test_load_available_groups_sorts_by_proximity_when_last_attributes_given(self, db_session):
        crud.clear_pending_pool(db_session)
        c = _constraints()
        _seed(db_session, seed=8, batches=5, constraints=c)

        fifo = crud.load_available_groups(db_session, limit=1000)
        assert len(fifo) >= 2
        # kasıtlı olarak FIFO'nun EN SONUNCU grubunu referans noktası yap --
        # eğer sıralama gerçekten işliyorsa, bu grup (veya ona en yakın olan)
        # artık proximity sonuçlarında EN ÖNDE olmalı (FIFO'da olduğu gibi en
        # sonda değil).
        target = fifo[-1]
        proximity = crud.load_available_groups(
            db_session, limit=1000, last_attributes=target.first, constraints=c,
        )
        assert len(proximity) == len(fifo)
        assert proximity[0].id == target.id  # kendisine mesafe 0 -> her zaman ilk sırada
        assert {g.id for g in proximity} == {g.id for g in fifo}  # aynı küme, farklı sıra

    def test_load_available_transitions_only_pending(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=2, batches=2)

        transitions = crud.load_available_transitions(db_session, limit=1000)
        assert transitions

        first_id = transitions[0].id
        crud.consume_transition_order(db_session, order_id=first_id)

        remaining = crud.load_available_transitions(db_session, limit=1000)
        assert first_id not in [t.id for t in remaining]
        assert len(remaining) == len(transitions) - 1


class TestConsumeGroupMembers:
    def test_consume_fewer_than_available_marks_partially_used(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=3, batches=1)
        group = crud.load_available_groups(db_session, limit=1)[0]
        assume_take = group.group_size - 1
        if assume_take <= 0:
            return  # bu tohumla grup zaten tek elemanlıysa test anlamsızlaşır, atla
        consumed = crud.consume_group_members(db_session, group_id=group.id, take=assume_take)
        assert len(consumed) == assume_take
        for order in consumed:
            assert order.status == "scheduled"
        row = db_session.get(MainProductGroup, group.id)
        assert row.status == "partially_used"
        assert row.group_size == group.group_size - assume_take

    def test_consume_all_marks_scheduled(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=4, batches=1)
        group = crud.load_available_groups(db_session, limit=1)[0]
        consumed = crud.consume_group_members(db_session, group_id=group.id, take=group.group_size)
        assert len(consumed) == group.group_size
        row = db_session.get(MainProductGroup, group.id)
        assert row.status == "scheduled"
        assert row.group_size == 0

    def test_consume_more_than_available_is_capped(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=5, batches=1)
        group = crud.load_available_groups(db_session, limit=1)[0]
        consumed = crud.consume_group_members(db_session, group_id=group.id, take=group.group_size + 1000)
        assert len(consumed) == group.group_size


class TestSumAvailableGroupSizes:
    def test_sums_only_nonzero_groups(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=6, batches=2)
        groups = crud.load_available_groups(db_session, limit=1000)
        expected = sum(g.group_size for g in groups)
        assert crud.sum_available_group_sizes(db_session) == expected

        # birini tamamen tüket -- toplam düşmeli
        crud.consume_group_members(db_session, group_id=groups[0].id, take=groups[0].group_size)
        assert crud.sum_available_group_sizes(db_session) == expected - groups[0].group_size


class TestEventsAndNotify:
    def test_emit_event_writes_row(self, db_session):
        row = crud.emit_event(db_session, event_type="order_generated", payload={"count": 5})
        assert row.id is not None
        assert row.event_type == "order_generated"
        assert row.payload == {"count": 5}

    def test_record_manager_and_worker_decision_round_trip(self, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=9, batches=1)
        group = crud.load_available_groups(db_session, limit=1)[0]
        transition = crud.load_available_transitions(db_session, limit=1)[0]
        course = crud.start_new_course(db_session, constraints=_constraints())

        m_decision = crud.record_manager_decision(
            db_session, course_id=course.id, step_index=0, vector=[1.0, 2.0],
            eligible_group_ids=[group.id], selected_group_id=group.id, reward=0.0, model_version_id=None,
        )
        assert m_decision.id is not None
        w_decision = crud.record_worker_decision(
            db_session, manager_decision_id=m_decision.id, course_id=course.id, step_index=0,
            vector=[0.5], eligible_transition_ids=[transition.id], selected_transition_order_id=transition.id,
            success=True, reward=12.5, model_version_id=None,
        )
        assert w_decision.manager_decision_id == m_decision.id
        assert w_decision.success is True


class TestSimulationRunRows:
    def test_create_and_status_transitions(self, db_session):
        run = crud.create_simulation_run(
            db_session, mode="hybrid", status="running", tick_interval_ms=500,
            manager_model_version_id=None, worker_model_version_id=None, config={"x": 1},
        )
        assert run.status == "running"
        assert run.config == {"x": 1}

        updated = crud.set_simulation_run_status(db_session, run.id, "paused")
        assert updated.status == "paused"

        stopped = crud.set_simulation_run_status(db_session, run.id, "stopped")
        assert stopped.status == "stopped"
        assert stopped.stopped_at is not None

    def test_get_latest_simulation_run(self, db_session):
        assert crud.get_latest_simulation_run(db_session) is None
        first = crud.create_simulation_run(
            db_session, mode="autonomous", status="running", tick_interval_ms=100,
            manager_model_version_id=None, worker_model_version_id=None,
        )
        second = crud.create_simulation_run(
            db_session, mode="autonomous", status="running", tick_interval_ms=100,
            manager_model_version_id=None, worker_model_version_id=None,
        )
        latest = crud.get_latest_simulation_run(db_session)
        assert latest.id == second.id
        assert latest.id != first.id
