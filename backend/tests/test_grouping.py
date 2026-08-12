"""domain/grouping.py birim testleri — Faz 2 (§2.2.2)."""

from app.domain.dto import SlabOrderDTO
from app.domain.grouping import classify_and_group


def _order(id_, steel_grade, width=1000.0, thickness=2.0, hardness=50.0, temp=850.0):
    return SlabOrderDTO(
        id=id_,
        steel_grade=steel_grade,
        width_mm=width,
        thickness_mm=thickness,
        hardness=hardness,
        heating_temp_c=temp,
        slab_width_mm=width,
        slab_thickness_mm=200.0,
        slab_length_mm=3000.0,
    )


def test_orders_with_transition_grade_become_transition_orders():
    orders = [_order(1, "TR1"), _order(2, "TR1")]
    groups, transitions = classify_and_group(orders, transition_grades={"TR1"})
    assert groups == []
    assert {t.id for t in transitions} == {1, 2}


def test_main_orders_with_same_spec_are_batched_into_one_group():
    orders = [
        _order(1, "Q235", width=1000.0, thickness=2.0, hardness=50.0, temp=850.0),
        _order(2, "Q235", width=1000.0, thickness=2.0, hardness=52.0, temp=852.0),
        _order(3, "Q235", width=1000.0, thickness=2.0, hardness=54.0, temp=854.0),
    ]
    groups, transitions = classify_and_group(orders, transition_grades=set())
    assert transitions == []
    assert len(groups) == 1
    group = groups[0]
    assert group.steel_grade == "Q235"
    assert group.group_size == 3
    assert group.initial_group_size == 3
    assert group.member_order_ids == (1, 2, 3)
    # eş. 26: first/last = grubun (girdi sırasına göre) ilk/son order öznitelikleri
    assert group.first.hardness == 50.0
    assert group.last.hardness == 54.0


def test_different_dimensions_create_separate_groups_even_with_same_grade():
    orders = [
        _order(1, "Q235", width=1000.0),
        _order(2, "Q235", width=1200.0),
    ]
    groups, _ = classify_and_group(orders, transition_grades=set())
    assert len(groups) == 2
    assert {g.group_size for g in groups} == {1, 1}


def test_non_contiguous_same_spec_orders_still_merge_into_one_group():
    orders = [
        _order(1, "Q235", width=1000.0),
        _order(2, "TR1", width=500.0),
        _order(3, "Q235", width=1000.0),
    ]
    groups, transitions = classify_and_group(orders, transition_grades={"TR1"})
    assert len(groups) == 1
    assert groups[0].group_size == 2
    assert groups[0].member_order_ids == (1, 3)
    assert len(transitions) == 1


def test_mixed_pool_produces_multiple_groups_and_transitions():
    orders = [
        _order(1, "Q235", width=1000.0),
        _order(2, "Q235", width=1000.0),
        _order(3, "Q345", width=1200.0),
        _order(4, "TR1", width=600.0),
    ]
    groups, transitions = classify_and_group(orders, transition_grades={"TR1"})
    assert len(groups) == 2
    assert len(transitions) == 1
    assert transitions[0].id == 4
    # grup id'leri girdi sırasına göre 1'den başlayan yerel sayaç
    assert [g.id for g in groups] == [1, 2]
