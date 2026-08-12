"""data_generation/generator.py birim testleri — Faz 3 (TASARIM.md §5, §12.4)."""

import itertools
import random

import pytest

from app.core.constraints import RollingConstraints
from app.data_generation.generator import (
    DEFAULT_CONFIG_PATH,
    Range,
    generate_batch,
    load_synthetic_config,
)
from app.domain.transition_rules import within_dimensional_tolerance


@pytest.fixture()
def config():
    return load_synthetic_config(DEFAULT_CONFIG_PATH)


@pytest.fixture()
def constraints():
    # backend/.env'deki gerçek DB seed değerleriyle tutarlı (Faz 3 sonrası Kz).
    return RollingConstraints(
        delta_w=50.0,
        delta_t=0.5,
        delta_h=5.0,
        delta_theta=30.0,
        kz=3_000_000.0,
        lr=3,
        m_min=60,
        m_max=100,
        soft_transition_limit=3,
    )


def _bridgeable_within_limit(prev, target, pool, constraints, limit):
    if within_dimensional_tolerance(prev, target, constraints):
        return True
    for length in range(1, limit + 1):
        for combo in itertools.permutations(pool, length):
            cur = prev
            ok = True
            for t in combo:
                if not within_dimensional_tolerance(cur, t.attributes, constraints):
                    ok = False
                    break
                cur = t.attributes
            if ok and within_dimensional_tolerance(cur, target, constraints):
                return True
    return False


class TestConfigLoading:
    def test_loads_expected_grades(self, config):
        assert "Q235B" in config.main_steel_grades
        assert "TR-C" in config.transition_steel_grades

    def test_main_and_transition_grades_are_disjoint(self, config):
        assert set(config.main_steel_grades).isdisjoint(config.transition_steel_grades)

    def test_range_sample_stays_within_bounds(self):
        r = Range(min=10.0, max=20.0)
        rng = random.Random(0)
        for _ in range(100):
            v = r.sample(rng)
            assert 10.0 <= v <= 20.0


class TestGenerateBatchShape:
    def test_reproducible_with_same_seed(self, config, constraints):
        batch1 = generate_batch(config, constraints, random.Random(42))
        batch2 = generate_batch(config, constraints, random.Random(42))
        assert [o.width_mm for o in batch1.orders] == [o.width_mm for o in batch2.orders]
        assert len(batch1.main_groups) == len(batch2.main_groups)

    def test_group_count_within_configured_range(self, config, constraints):
        for seed in range(30):
            batch = generate_batch(config, constraints, random.Random(seed))
            assert int(config.main_groups_per_course.min) <= len(batch.main_groups) <= int(
                config.main_groups_per_course.max
            )

    def test_group_sizes_within_configured_range(self, config, constraints):
        for seed in range(30):
            batch = generate_batch(config, constraints, random.Random(seed))
            for group in batch.main_groups:
                assert int(config.group_size.min) <= group.group_size <= int(config.group_size.max)

    def test_orders_total_matches_groups_plus_transitions(self, config, constraints):
        batch = generate_batch(config, constraints, random.Random(7))
        main_order_count = sum(g.group_size for g in batch.main_groups)
        assert main_order_count + len(batch.transitions) == len(batch.orders)

    def test_all_transition_orders_use_transition_grades(self, config, constraints):
        batch = generate_batch(config, constraints, random.Random(7))
        for t in batch.transitions:
            assert t.steel_grade in config.transition_steel_grades

    def test_main_group_members_share_identical_width_and_thickness(self, config, constraints):
        # grouping.py'nin batching anahtarı (steel_grade, width_mm, thickness_mm)
        # tam eşleşme gerektirir -- generator bunu ihlal etmemeli.
        batch = generate_batch(config, constraints, random.Random(7))
        assert batch.main_groups[0].first.width_mm == batch.main_groups[0].last.width_mm
        assert batch.main_groups[0].first.thickness_mm == batch.main_groups[0].last.thickness_mm


class TestBridgeFeasibilityGuarantee:
    """§5'in ana gereksinimi: ardışık ana gruplar arasındaki farklar,
    çoğu durumda ≤3 geçiş slabıyla köprülenebilecek şekilde kurgulanmalıdır
    -- aksi halde worker hiçbir zaman başarılı olamaz."""

    def test_consecutive_main_groups_are_always_bridgeable_within_soft_limit(self, config, constraints):
        checked_pairs = 0
        for seed in range(300):
            batch = generate_batch(config, constraints, random.Random(seed))
            if len(batch.main_groups) < 2:
                continue
            for i in range(len(batch.main_groups) - 1):
                g1, g2 = batch.main_groups[i], batch.main_groups[i + 1]
                checked_pairs += 1
                assert _bridgeable_within_limit(
                    g1.last, g2.first, list(batch.transitions), constraints, constraints.soft_transition_limit
                ), f"seed={seed} pair={i} koprulenemedi"
        assert checked_pairs > 50  # testin gercekten K=2 durumlarini kapsadigindan emin ol
