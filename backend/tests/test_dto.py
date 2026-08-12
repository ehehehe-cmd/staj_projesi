"""domain/dto.py birim testleri — Faz 2."""

from app.domain.dto import (
    MainGroupDTO,
    OrderAttributes,
    SlabOrderDTO,
    TransitionOrderDTO,
    compute_theoretical_rolling_length,
)


def test_compute_theoretical_rolling_length_matches_table2_formula():
    # l_i = (W_i * T_i * L_i) / (w_i * t_i) -- Table 2
    result = compute_theoretical_rolling_length(
        slab_width_mm=1000.0,
        slab_thickness_mm=200.0,
        slab_length_mm=3000.0,
        width_mm=1000.0,
        thickness_mm=2.0,
    )
    assert result == (1000.0 * 200.0 * 3000.0) / (1000.0 * 2.0)


def test_slab_order_rolling_length_uses_precomputed_value_when_present():
    order = SlabOrderDTO(
        id=1,
        steel_grade="Q235",
        width_mm=1000.0,
        thickness_mm=2.0,
        hardness=50.0,
        heating_temp_c=850.0,
        slab_width_mm=1000.0,
        slab_thickness_mm=200.0,
        slab_length_mm=3000.0,
        theoretical_rolling_length=999999.0,
    )
    assert order.rolling_length() == 999999.0


def test_slab_order_rolling_length_computes_when_absent():
    order = SlabOrderDTO(
        id=1,
        steel_grade="Q235",
        width_mm=1000.0,
        thickness_mm=2.0,
        hardness=50.0,
        heating_temp_c=850.0,
        slab_width_mm=1000.0,
        slab_thickness_mm=200.0,
        slab_length_mm=3000.0,
    )
    expected = compute_theoretical_rolling_length(
        slab_width_mm=1000.0, slab_thickness_mm=200.0, slab_length_mm=3000.0, width_mm=1000.0, thickness_mm=2.0
    )
    assert order.rolling_length() == expected


def test_slab_order_attributes_property():
    order = SlabOrderDTO(
        id=1,
        steel_grade="Q235",
        width_mm=1000.0,
        thickness_mm=2.0,
        hardness=50.0,
        heating_temp_c=850.0,
        slab_width_mm=1000.0,
        slab_thickness_mm=200.0,
        slab_length_mm=3000.0,
    )
    assert order.attributes == OrderAttributes(width_mm=1000.0, thickness_mm=2.0, hardness=50.0, heating_temp_c=850.0)


def test_main_group_is_exhausted():
    group = MainGroupDTO(
        id=1,
        steel_grade="Q235",
        first=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        last=OrderAttributes(1000.0, 2.0, 51.0, 851.0),
        group_size=0,
        initial_group_size=5,
    )
    assert group.is_exhausted() is True

    group2 = MainGroupDTO(
        id=2,
        steel_grade="Q235",
        first=OrderAttributes(1000.0, 2.0, 50.0, 850.0),
        last=OrderAttributes(1000.0, 2.0, 51.0, 851.0),
        group_size=3,
        initial_group_size=5,
    )
    assert group2.is_exhausted() is False


def test_transition_order_attributes_property():
    t = TransitionOrderDTO(id=9, steel_grade="TR1", width_mm=800.0, thickness_mm=1.5, hardness=40.0, heating_temp_c=900.0)
    assert t.attributes == OrderAttributes(800.0, 1.5, 40.0, 900.0)
