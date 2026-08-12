"""domain/action_mask.py birim testleri — Faz 2 (eş. 8-25)."""

import pytest

from app.core.constraints import RollingConstraints
from app.domain.action_mask import CourseProgress, manager_action_mask, worker_action_mask
from app.domain.dto import MainGroupDTO, OrderAttributes, TransitionOrderDTO


@pytest.fixture()
def constraints():
    return RollingConstraints(
        delta_w=50.0,
        delta_t=0.5,
        delta_h=5.0,
        delta_theta=30.0,
        kz=50000.0,
        lr=3,
        m_min=60,
        m_max=100,
        soft_transition_limit=3,
    )


def _group(id_, size, w=1000.0, t=2.0):
    attrs = OrderAttributes(w, t, 50.0, 850.0)
    return MainGroupDTO(id=id_, steel_grade="Q235", first=attrs, last=attrs, group_size=size, initial_group_size=size)


def _transition(id_, w=1000.0, t=2.0, h=50.0, temp=850.0):
    return TransitionOrderDTO(id=id_, steel_grade="TR1", width_mm=w, thickness_mm=t, hardness=h, heating_temp_c=temp)


class TestManagerActionMask:
    def test_exhausted_group_is_masked_out(self):
        groups = [_group(1, size=0), _group(2, size=5)]
        progress = CourseProgress(
            order_count=10, max_orders=100, cumulative_length_mm=0.0, reverse_width_events_count=0, last_attributes=None
        )
        mask = manager_action_mask(groups, progress)
        assert mask == {1: False, 2: True}

    def test_course_at_capacity_masks_everything(self):
        groups = [_group(1, size=5), _group(2, size=5)]
        progress = CourseProgress(
            order_count=100, max_orders=100, cumulative_length_mm=0.0, reverse_width_events_count=0, last_attributes=None
        )
        mask = manager_action_mask(groups, progress)
        assert mask == {1: False, 2: False}

    def test_empty_groups_yields_empty_mask(self):
        progress = CourseProgress(
            order_count=0, max_orders=100, cumulative_length_mm=0.0, reverse_width_events_count=0, last_attributes=None
        )
        assert manager_action_mask([], progress) == {}


class TestWorkerActionMask:
    def test_used_transition_is_masked_out(self, constraints):
        transitions = [_transition(1), _transition(2)]
        progress = CourseProgress(
            order_count=10,
            max_orders=100,
            cumulative_length_mm=1000.0,
            reverse_width_events_count=0,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        mask = worker_action_mask(transitions, used_transition_order_ids={1}, progress=progress, constraints=constraints)
        assert mask[1] is False
        assert mask[2] is True

    def test_infeasible_dimensional_jump_is_masked_out(self, constraints):
        transitions = [_transition(1, w=1500.0)]  # delta_w=50 asilir
        progress = CourseProgress(
            order_count=10,
            max_orders=100,
            cumulative_length_mm=1000.0,
            reverse_width_events_count=0,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        mask = worker_action_mask(transitions, used_transition_order_ids=set(), progress=progress, constraints=constraints)
        assert mask[1] is False

    def test_reverse_width_over_budget_is_masked_out(self, constraints):
        transitions = [_transition(1, w=960.0)]  # 40mm azalis -> tolerans icinde ama reverse
        progress = CourseProgress(
            order_count=10,
            max_orders=100,
            cumulative_length_mm=1000.0,  # bolge ici (Kz altinda)
            reverse_width_events_count=constraints.lr,  # butce dolu
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        mask = worker_action_mask(transitions, used_transition_order_ids=set(), progress=progress, constraints=constraints)
        assert mask[1] is False

    def test_feasible_transition_is_allowed(self, constraints):
        transitions = [_transition(1, w=1020.0)]
        progress = CourseProgress(
            order_count=10,
            max_orders=100,
            cumulative_length_mm=1000.0,
            reverse_width_events_count=0,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        mask = worker_action_mask(transitions, used_transition_order_ids=set(), progress=progress, constraints=constraints)
        assert mask[1] is True

    def test_no_last_attributes_allows_all_unused(self, constraints):
        transitions = [_transition(1), _transition(2)]
        progress = CourseProgress(
            order_count=0, max_orders=100, cumulative_length_mm=0.0, reverse_width_events_count=0, last_attributes=None
        )
        mask = worker_action_mask(transitions, used_transition_order_ids={2}, progress=progress, constraints=constraints)
        assert mask == {1: True, 2: False}

    def test_course_at_capacity_masks_all_transitions(self, constraints):
        transitions = [_transition(1)]
        progress = CourseProgress(
            order_count=100,
            max_orders=100,
            cumulative_length_mm=1000.0,
            reverse_width_events_count=0,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        mask = worker_action_mask(transitions, used_transition_order_ids=set(), progress=progress, constraints=constraints)
        assert mask == {1: False}
