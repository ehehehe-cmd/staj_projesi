"""training/evaluate.py duman testi — TASARIM.md §14.1.C.

Küçük ölçekli (tiny hyperparams/tiny env, birkaç epizot) uçtan uca çağrı:
checkpoint kaydet -> evaluate()/compare_against_random() çökmeden N sonuç
döndürüyor mu. Gerçek eğitilmiş bir politika kalitesini DOĞRULAMAZ — yalnızca
CLI/fonksiyonların bozulmadığını kontrol eden bir pipeline testidir (aynı
``test_train_integration.py``'nin disipliniyle).
"""

from __future__ import annotations

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, load_synthetic_config
from app.training.agents.dqn_agent import DQNHyperparams
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent
from app.training.env import RewardWeights
from app.training.evaluate import compare_against_random, evaluate
from app.training.train import TrainingConfig

COURSES_PER_EPISODE = 2
K_MAX = 4
P_MAX = 30


def _tiny_hyperparams() -> DQNHyperparams:
    return DQNHyperparams(
        hidden_dim=16, learning_rate=1e-2, gamma=0.9, batch_size=8,
        target_update_interval=5, replay_capacity=500, min_replay_size=8,
        epsilon_start=1.0, epsilon_end=0.5, epsilon_decay_steps=50,
    )


def _tiny_cfg() -> TrainingConfig:
    return TrainingConfig(
        seed=1, episodes=3, courses_per_episode=COURSES_PER_EPISODE, k_max=K_MAX, p_max=P_MAX,
        max_manager_steps_per_course=20, max_worker_steps_per_subtask=10,
        hyperparams=_tiny_hyperparams(),
        reward_weights=RewardWeights(omega1=1.0, omega2=1.0, r_s=10.0, beta0=5.0, beta1=1.0, beta2=2.0),
    )


def _constraints() -> RollingConstraints:
    return RollingConstraints(
        delta_w=50.0, delta_t=0.5, delta_h=5.0, delta_theta=30.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )


def _save_tiny_checkpoints(tmp_path):
    hp = _tiny_hyperparams()
    manager_agent = build_manager_agent(k_max=K_MAX, hyperparams=hp, seed=1)
    worker_agent = build_worker_agent(k_max=K_MAX, p_max=P_MAX, hyperparams=hp, seed=1)
    m_path = tmp_path / "manager.pt"
    w_path = tmp_path / "worker.pt"
    manager_agent.save_checkpoint(m_path)
    worker_agent.save_checkpoint(w_path)
    return m_path, w_path


class TestEvaluateGreedy:
    def test_returns_one_result_per_episode(self, tmp_path):
        m_path, w_path = _save_tiny_checkpoints(tmp_path)
        results = evaluate(
            cfg=_tiny_cfg(), synthetic_config=load_synthetic_config(DEFAULT_CONFIG_PATH), constraints=_constraints(),
            manager_checkpoint=m_path, worker_checkpoint=w_path, episodes=3, seed=1,
        )
        assert len(results) == 3
        for r in results:
            assert 0.0 <= r["coverage_ratio"] <= 1.0
            assert 0.0 <= r["completion_rate"] <= 1.0


class TestCompareAgainstRandom:
    def test_paired_comparison_does_not_crash_and_has_matching_lengths(self, tmp_path):
        m_path, w_path = _save_tiny_checkpoints(tmp_path)
        result = compare_against_random(
            cfg=_tiny_cfg(), synthetic_config=load_synthetic_config(DEFAULT_CONFIG_PATH), constraints=_constraints(),
            manager_checkpoint=m_path, worker_checkpoint=w_path, episodes=3, seed=1,
        )
        assert len(result["trained_coverage"]) == 3
        assert len(result["random_coverage"]) == 3
        assert len(result["trained_completion"]) == 3
        assert len(result["random_completion"]) == 3
        assert isinstance(result["coverage_t_stat"], float)
        assert isinstance(result["completion_t_stat"], float)

    def test_courses_per_episode_override_changes_course_count(self, tmp_path):
        m_path, w_path = _save_tiny_checkpoints(tmp_path)
        from dataclasses import replace

        cfg = replace(_tiny_cfg(), courses_per_episode=5)
        result = compare_against_random(
            cfg=cfg, synthetic_config=load_synthetic_config(DEFAULT_CONFIG_PATH), constraints=_constraints(),
            manager_checkpoint=m_path, worker_checkpoint=w_path, episodes=2, seed=1,
        )
        assert len(result["trained_coverage"]) == 2
