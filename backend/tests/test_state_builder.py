"""domain/state_builder.py birim testleri — Faz 2 (eş. 28-29, K_max/P_max padding)."""

from app.domain.dto import MainGroupDTO, OrderAttributes, TransitionOrderDTO
from app.domain.state_builder import build_manager_state, build_worker_state


def _group(id_, size, w=1000.0):
    first = OrderAttributes(w, 2.0, 50.0, 850.0)
    last = OrderAttributes(w, 2.0, 55.0, 855.0)
    return MainGroupDTO(id=id_, steel_grade="Q235", first=first, last=last, group_size=size, initial_group_size=size)


def _transition(id_, w=800.0):
    return TransitionOrderDTO(id=id_, steel_grade="TR1", width_mm=w, thickness_mm=1.5, hardness=40.0, heating_temp_c=900.0)


class TestManagerState:
    def test_vector_length_matches_k_max_padding(self):
        groups = [_group(1, 5), _group(2, 3)]
        state = build_manager_state(
            groups,
            reverse_width_capability=True,
            order_count=8,
            course_index=2,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        k_max = 5
        vector = state.to_vector(k_max)
        # k_max*9 (grup) + 1 (H_N) + 1 (I_m) + 1 (J) + 4 (s_t)
        assert len(vector) == k_max * 9 + 1 + 1 + 1 + 4

    def test_padding_slots_are_zero(self):
        groups = [_group(1, 5)]
        state = build_manager_state(
            groups, reverse_width_capability=False, order_count=0, course_index=1, last_attributes=None
        )
        vector = state.to_vector(3)
        # ilk grup (9 deger) dolu, sonraki 2 grup slotu (18 deger) sifir olmali
        padding_region = vector[9:27]
        assert padding_region == [0.0] * 18

    def test_truncation_when_more_groups_than_k_max(self):
        groups = [_group(i, 1) for i in range(1, 6)]
        state = build_manager_state(
            groups, reverse_width_capability=True, order_count=0, course_index=0, last_attributes=None
        )
        mask = state.group_mask(3)
        assert mask == [True, True, True]

    def test_group_mask_reflects_available_count(self):
        groups = [_group(1, 5)]
        state = build_manager_state(
            groups, reverse_width_capability=True, order_count=0, course_index=0, last_attributes=None
        )
        assert state.group_mask(4) == [True, False, False, False]

    def test_reverse_capability_and_scalars_present_in_vector(self):
        state = build_manager_state(
            [], reverse_width_capability=True, order_count=7, course_index=2, last_attributes=None
        )
        vector = state.to_vector(0)
        # k_max=0 -> grup blogu yok; kalan: H_N, I_m, J, s_t(4)
        assert vector[0] == 1.0  # H_N
        assert vector[1] == 7.0  # I_m
        assert vector[2] == 2.0  # J
        assert vector[3:7] == [0.0, 0.0, 0.0, 0.0]  # s_t yok -> sifir


class TestWorkerState:
    def test_vector_length_matches_k_max_p_max_padding(self):
        transitions = [_transition(1), _transition(2)]
        groups = [_group(1, 5)]
        state = build_worker_state(
            transitions,
            groups,
            used_transition_count=1,
            reverse_width_event_count=0,
            reverse_width_capability=True,
            last_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
            target_attributes=OrderAttributes(1010.0, 2.0, 51.0, 851.0),
        )
        k_max, p_max = 4, 6
        vector = state.to_vector(k_max=k_max, p_max=p_max)
        # p_max*4 (M) + k_max*9 (N) + 1 (I_W) + 1 (H_M) + 1 (H_N) + 4 (s_t) + 4 (s_target)
        assert len(vector) == p_max * 4 + k_max * 9 + 1 + 1 + 1 + 4 + 4

    def test_transition_mask_reflects_available_count(self):
        transitions = [_transition(1), _transition(2), _transition(3)]
        state = build_worker_state(
            transitions,
            [],
            used_transition_count=0,
            reverse_width_event_count=0,
            reverse_width_capability=True,
            last_attributes=None,
            target_attributes=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        )
        assert state.transition_mask(5) == [True, True, True, False, False]
        assert state.transition_mask(2) == [True, True]

    def test_target_attributes_always_present_even_without_padding(self):
        state = build_worker_state(
            [],
            [],
            used_transition_count=0,
            reverse_width_event_count=2,
            reverse_width_capability=False,
            last_attributes=None,
            target_attributes=OrderAttributes(1234.0, 5.0, 60.0, 900.0),
        )
        vector = state.to_vector(k_max=0, p_max=0)
        # M blok yok, N blok yok -> kalan: I_W, H_M, H_N, s_t(4), s_target(4)
        assert vector == [0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1234.0, 5.0, 60.0, 900.0]
