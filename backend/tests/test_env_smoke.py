"""training/env.py birim/smoke testleri — Faz 4 (TASARIM.md §4: "birkaç
epizodu uçtan uca hatasız çalıştırır"). DB'ye HİÇ dokunmaz (§1 ilke 2).
"""

from __future__ import annotations

import random

import pytest

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, load_synthetic_config
from app.training.env import DecisionKind, HotRollingEnv, RewardWeights

COURSES_PER_EPISODE = 2
K_MAX = 4  # courses_per_episode(2) * main_groups_per_course.max(2)
P_MAX = 30  # courses_per_episode(2) * (decoy.max(10) + soft_transition_limit(3)) güvenlik payıyla


@pytest.fixture()
def synthetic_config():
    return load_synthetic_config(DEFAULT_CONFIG_PATH)


@pytest.fixture()
def constraints():
    return RollingConstraints(
        delta_w=50.0, delta_t=0.5, delta_h=5.0, delta_theta=30.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )


@pytest.fixture()
def reward_weights():
    return RewardWeights(
        omega1=1.0, omega2=1.0, r_s=10.0, beta0=5.0, beta1=1.0, beta2=2.0, m_target=100.0, omega3=0.1
    )


def _make_env(synthetic_config, constraints, reward_weights, **overrides) -> HotRollingEnv:
    kwargs = dict(
        synthetic_config=synthetic_config,
        constraints=constraints,
        reward_weights=reward_weights,
        courses_per_episode=COURSES_PER_EPISODE,
        k_max=K_MAX,
        p_max=P_MAX,
    )
    kwargs.update(overrides)
    return HotRollingEnv(**kwargs)


def _run_random_episode(env: HotRollingEnv, *, seed: int, rng: random.Random, max_steps: int = 5000) -> tuple[dict, bool]:
    """Maskeye saygılı, tamamen rastgele bir politika ile bir epizodu sonuna
    kadar çalıştırır. Döner: (episode_summary_info, worker_phase_seen)."""
    obs = env.reset(seed=seed)
    info: dict = {}
    worker_seen = False
    for _ in range(max_steps):
        if obs.kind is DecisionKind.WORKER:
            worker_seen = True
        valid = [i for i, ok in enumerate(obs.mask) if ok]
        assert valid, "gözlemlenen mask boş olmamalı (env boş maskeyi hiç dışarı vermemeli)"
        action = rng.choice(valid)
        result = env.step(action)
        info = result.info or info
        if result.next_observation is None:
            assert result.episode_done
            return info, worker_seen
        obs = result.next_observation
    raise AssertionError("epizot max_steps içinde bitmedi — olası sonsuz döngü")


class TestResetObservation:
    def test_vector_and_mask_dimensions(self, synthetic_config, constraints, reward_weights):
        env = _make_env(synthetic_config, constraints, reward_weights)
        obs = env.reset(seed=1)
        assert obs.kind is DecisionKind.MANAGER
        assert len(obs.mask) == K_MAX
        # ManagerState.to_vector(k_max) = k_max*9 (grup) + 1(H_N) + 1(I_m) + 1(J) + 4(s_t)
        assert len(obs.vector) == K_MAX * 9 + 7

    def test_deterministic_given_same_seed(self, synthetic_config, constraints, reward_weights):
        env1 = _make_env(synthetic_config, constraints, reward_weights)
        env2 = _make_env(synthetic_config, constraints, reward_weights)
        obs1 = env1.reset(seed=42)
        obs2 = env2.reset(seed=42)
        assert obs1.vector == pytest.approx(obs2.vector)
        assert obs1.mask == obs2.mask

    def test_different_seeds_generally_differ(self, synthetic_config, constraints, reward_weights):
        env = _make_env(synthetic_config, constraints, reward_weights)
        obs1 = env.reset(seed=1)
        obs2 = env.reset(seed=2)
        assert obs1.vector != obs2.vector


class TestInvalidAction:
    def test_masked_out_action_raises(self, synthetic_config, constraints, reward_weights):
        env = _make_env(synthetic_config, constraints, reward_weights)
        obs = env.reset(seed=1)
        invalid_indices = [i for i, ok in enumerate(obs.mask) if not ok]
        assert invalid_indices, "test anlamlı olsun diye en az bir maskelenmiş pozisyon olmalı (K_MAX > grup sayısı)"
        with pytest.raises(ValueError):
            env.step(invalid_indices[0])

    def test_out_of_range_action_raises(self, synthetic_config, constraints, reward_weights):
        env = _make_env(synthetic_config, constraints, reward_weights)
        env.reset(seed=1)
        with pytest.raises(ValueError):
            env.step(999)


class TestFullEpisodes:
    @pytest.mark.parametrize("seed", list(range(10)))
    def test_random_episode_terminates_with_valid_summary(self, synthetic_config, constraints, reward_weights, seed):
        env = _make_env(synthetic_config, constraints, reward_weights)
        rng = random.Random(1000 + seed)
        info, _ = _run_random_episode(env, seed=seed, rng=rng)

        assert 0 <= info["main_orders_used"] <= info["main_orders_total"]
        assert 0.0 <= info["coverage_ratio"] <= 1.0
        assert len(info["course_order_counts"]) == COURSES_PER_EPISODE
        for count in info["course_order_counts"].values():
            assert 0 <= count <= constraints.m_max

    def test_worker_phase_is_reached_across_several_episodes(self, synthetic_config, constraints, reward_weights):
        """Üretici, ardışık ana gruplar arasında ≤3 order'lık bir köprü
        garantiliyor (Faz 3) — bu yüzden en az bir epizotta worker devreye
        girmelidir; aksi hâlde HRL'nin worker seviyesi hiç egzersiz
        edilmiyor demektir (ciddi bir tasarım/kablolama hatası olurdu)."""
        env = _make_env(synthetic_config, constraints, reward_weights)
        any_worker_seen = False
        for seed in range(10):
            rng = random.Random(2000 + seed)
            _, worker_seen = _run_random_episode(env, seed=seed, rng=rng)
            any_worker_seen = any_worker_seen or worker_seen
        assert any_worker_seen

    def test_episode_never_exceeds_manager_step_cap_indefinitely(self, synthetic_config, constraints, reward_weights):
        env = _make_env(synthetic_config, constraints, reward_weights, max_manager_steps_per_course=3)
        rng = random.Random(7)
        info, _ = _run_random_episode(env, seed=7, rng=rng, max_steps=2000)
        assert len(info["course_order_counts"]) == COURSES_PER_EPISODE


class TestSingleCourseEpisode:
    def test_k_max_smaller_than_pool_still_produces_fixed_size_vector(self, synthetic_config, constraints, reward_weights):
        """k_max havuzdaki gerçek grup sayısından küçük olsa bile (kesme/
        truncation) vektör boyutu sabit kalmalı — state_builder padding'i."""
        env = _make_env(synthetic_config, constraints, reward_weights, k_max=1, p_max=5)
        obs = env.reset(seed=3)
        assert len(obs.mask) == 1
        assert len(obs.vector) == 1 * 9 + 7
