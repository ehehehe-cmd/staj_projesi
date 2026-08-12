"""domain/transition_rules.py birim testleri — Faz 2 (eş. 17-25)."""

import pytest

from app.core.constraints import RollingConstraints
from app.domain.dto import MainGroupDTO, OrderAttributes
from app.domain.transition_rules import (
    dimensional_distance,
    in_reverse_zone,
    is_reverse_width_step,
    is_transition_required,
    reverse_width_budget_available,
    reverse_width_capability,
    sort_groups_by_proximity,
    width_step_is_feasible,
    within_dimensional_tolerance,
)


@pytest.fixture()
def constraints():
    # TASARIM.md §12.2.3.1'deki (Faz 1) YER TUTUCU seed değerleriyle tutarlı.
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


class TestWithinDimensionalTolerance:
    def test_all_within_tolerance(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        cand = OrderAttributes(1040.0, 2.4, 54.0, 870.0)
        assert within_dimensional_tolerance(prev, cand, constraints) is True

    def test_width_jump_exceeds_tolerance(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        cand = OrderAttributes(1200.0, 2.0, 50.0, 850.0)
        assert within_dimensional_tolerance(prev, cand, constraints) is False

    @pytest.mark.parametrize(
        "field_index,delta_key",
        [(0, "delta_w"), (1, "delta_t"), (2, "delta_h"), (3, "delta_theta")],
    )
    def test_exact_boundary_is_still_feasible(self, constraints, field_index, delta_key):
        base = [1000.0, 2.0, 50.0, 850.0]
        delta = getattr(constraints, delta_key)
        candidate_values = list(base)
        candidate_values[field_index] += delta
        prev = OrderAttributes(*base)
        cand = OrderAttributes(*candidate_values)
        assert within_dimensional_tolerance(prev, cand, constraints) is True

    def test_negative_direction_also_checked(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        cand = OrderAttributes(800.0, 2.0, 50.0, 850.0)
        assert within_dimensional_tolerance(prev, cand, constraints) is False


class TestTransitionRequired:
    def test_not_required_when_within_tolerance(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        target = OrderAttributes(1010.0, 2.1, 51.0, 855.0)
        assert is_transition_required(prev, target, constraints) is False

    def test_required_when_outside_tolerance(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        target = OrderAttributes(1500.0, 2.0, 50.0, 850.0)
        assert is_transition_required(prev, target, constraints) is True


class TestReverseWidthStep:
    def test_decrease_is_reverse(self):
        assert is_reverse_width_step(1000.0, 900.0) is True

    def test_increase_is_not_reverse(self):
        assert is_reverse_width_step(900.0, 1000.0) is False

    def test_equal_is_not_reverse(self):
        assert is_reverse_width_step(1000.0, 1000.0) is False


class TestReverseZone:
    def test_below_kz_is_in_zone(self, constraints):
        assert in_reverse_zone(10000.0, constraints) is True

    def test_at_or_above_kz_is_out_of_zone(self, constraints):
        assert in_reverse_zone(constraints.kz, constraints) is False
        assert in_reverse_zone(constraints.kz + 1, constraints) is False

    def test_budget_available_below_lr(self, constraints):
        assert reverse_width_budget_available(0, constraints) is True
        assert reverse_width_budget_available(constraints.lr - 1, constraints) is True

    def test_budget_exhausted_at_lr(self, constraints):
        assert reverse_width_budget_available(constraints.lr, constraints) is False


class TestWidthStepIsFeasible:
    def test_increase_in_zone_always_feasible(self, constraints):
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=1040.0,
            cumulative_length_mm=1000.0,
            reverse_events_in_zone=constraints.lr,  # bütçe dolu olsa bile artış serbest
            constraints=constraints,
        ) is True

    def test_reverse_in_zone_feasible_under_budget(self, constraints):
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=960.0,
            cumulative_length_mm=1000.0,
            reverse_events_in_zone=0,
            constraints=constraints,
        ) is True

    def test_reverse_in_zone_infeasible_over_budget(self, constraints):
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=960.0,
            cumulative_length_mm=1000.0,
            reverse_events_in_zone=constraints.lr,
            constraints=constraints,
        ) is False

    def test_increase_beyond_zone_is_infeasible(self, constraints):
        # eş. 25: bölge dışında genişlik artamaz.
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=1010.0,
            cumulative_length_mm=constraints.kz + 100,
            reverse_events_in_zone=0,
            constraints=constraints,
        ) is False

    def test_decrease_beyond_zone_is_feasible_and_uncapped(self, constraints):
        # Bölge dışı azalışlar Lr bütçesine dahil değildir (eş. 24: yalnız b_jk=1 sayılır).
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=900.0,
            cumulative_length_mm=constraints.kz + 100,
            reverse_events_in_zone=constraints.lr,
            constraints=constraints,
        ) is True

    def test_equal_width_beyond_zone_is_feasible(self, constraints):
        assert width_step_is_feasible(
            prev_width_mm=1000.0,
            next_width_mm=1000.0,
            cumulative_length_mm=constraints.kz + 100,
            reverse_events_in_zone=0,
            constraints=constraints,
        ) is True


class TestReverseWidthCapability:
    def test_true_before_first_main_group_placed(self):
        assert reverse_width_capability(first_main_group_placed=False) is True

    def test_false_after_first_main_group_placed(self):
        assert reverse_width_capability(first_main_group_placed=True) is False


def _group(id_, first: OrderAttributes, last: OrderAttributes | None = None) -> MainGroupDTO:
    return MainGroupDTO(id=id_, steel_grade="Q235", first=first, last=last or first, group_size=10, initial_group_size=10)


class TestDimensionalDistance:
    def test_identical_attributes_have_zero_distance(self, constraints):
        attrs = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        assert dimensional_distance(attrs, attrs, constraints) == 0.0

    def test_distance_scales_with_delta_normalization(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        # tam olarak delta_w kadar uzak -> normalize skor katkısı 1.0
        cand = OrderAttributes(1000.0 + constraints.delta_w, 2.0, 50.0, 850.0)
        assert dimensional_distance(prev, cand, constraints) == pytest.approx(1.0)

    def test_farther_candidate_has_larger_distance(self, constraints):
        prev = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        near = OrderAttributes(1010.0, 2.0, 50.0, 850.0)
        far = OrderAttributes(1100.0, 2.0, 50.0, 850.0)
        assert dimensional_distance(prev, near, constraints) < dimensional_distance(prev, far, constraints)


class TestSortGroupsByProximity:
    def test_none_last_attributes_preserves_original_order(self, constraints):
        g1 = _group(1, OrderAttributes(1000.0, 2.0, 50.0, 850.0))
        g2 = _group(2, OrderAttributes(2000.0, 2.0, 50.0, 850.0))
        assert sort_groups_by_proximity([g2, g1], None, constraints) == [g2, g1]

    def test_closest_group_comes_first(self, constraints):
        last_attrs = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        far = _group(1, OrderAttributes(1400.0, 2.0, 50.0, 850.0))
        near = _group(2, OrderAttributes(1010.0, 2.0, 50.0, 850.0))
        mid = _group(3, OrderAttributes(1100.0, 2.0, 50.0, 850.0))
        # bilerek FIFO/id sirasindan FARKLI bir girdi sirasi (far, near, mid)
        ordered = sort_groups_by_proximity([far, near, mid], last_attrs, constraints)
        assert [g.id for g in ordered] == [2, 3, 1]

    def test_does_not_mutate_input_list(self, constraints):
        last_attrs = OrderAttributes(1000.0, 2.0, 50.0, 850.0)
        far = _group(1, OrderAttributes(1400.0, 2.0, 50.0, 850.0))
        near = _group(2, OrderAttributes(1010.0, 2.0, 50.0, 850.0))
        original = [far, near]
        sort_groups_by_proximity(original, last_attrs, constraints)
        assert original == [far, near]
