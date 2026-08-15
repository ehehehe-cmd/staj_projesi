"""training/train.py uçtan uca (küçük ölçekli) entegrasyon testi — Faz 4.

DB'ye dokunmaz (``run_training`` saf) — yalnızca ``conftest.py``'nin
session-scope ``_verify_schema_applied`` fixture'ı (Faz 1'den beri tüm test
paketi için ortak) gerçek Postgres'in ayakta olmasını gerektirir.
"""

from __future__ import annotations

import torch

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, load_synthetic_config
from app.training.agents.dqn_agent import DQNHyperparams
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent
from app.training.env import HotRollingEnv, RewardWeights
from app.training.train import EpisodeStats, run_training

COURSES_PER_EPISODE = 2
K_MAX = 4
P_MAX = 30


def _tiny_hyperparams() -> DQNHyperparams:
    return DQNHyperparams(
        hidden_dim=16,
        learning_rate=1e-2,
        gamma=0.9,
        batch_size=8,
        target_update_interval=5,
        replay_capacity=500,
        min_replay_size=8,
        epsilon_start=1.0,
        epsilon_end=0.5,
        epsilon_decay_steps=50,
    )


def _build_env() -> HotRollingEnv:
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    constraints = RollingConstraints(
        delta_w=50.0, delta_t=0.5, delta_h=5.0, delta_theta=30.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    weights = RewardWeights(
        omega1=1.0, omega2=1.0, r_s=10.0, beta0=5.0, beta1=1.0, beta2=2.0, m_target=100.0, omega3=0.1
    )
    return HotRollingEnv(
        synthetic_config=config, constraints=constraints, reward_weights=weights,
        courses_per_episode=COURSES_PER_EPISODE, k_max=K_MAX, p_max=P_MAX,
    )


class TestRunTraining:
    def test_runs_n_episodes_without_crashing_and_returns_stats(self):
        env = _build_env()
        hp = _tiny_hyperparams()
        manager_agent = build_manager_agent(k_max=K_MAX, hyperparams=hp, seed=1)
        worker_agent = build_worker_agent(k_max=K_MAX, p_max=P_MAX, hyperparams=hp, seed=1)

        stats = run_training(env=env, manager_agent=manager_agent, worker_agent=worker_agent, episodes=8, seed=100)

        assert len(stats) == 8
        assert all(isinstance(s, EpisodeStats) for s in stats)
        assert all(0.0 <= s.coverage_ratio <= 1.0 for s in stats)
        assert len(manager_agent.replay) > 0

    def test_train_step_produces_loss_once_min_replay_reached(self):
        env = _build_env()
        hp = _tiny_hyperparams()
        manager_agent = build_manager_agent(k_max=K_MAX, hyperparams=hp, seed=2)
        worker_agent = build_worker_agent(k_max=K_MAX, p_max=P_MAX, hyperparams=hp, seed=2)

        stats = run_training(env=env, manager_agent=manager_agent, worker_agent=worker_agent, episodes=15, seed=200)

        # manager her epizotta en az bir karar verir -> birkaç epizot sonra replay dolar ve loss hesaplanır.
        assert any(s.manager_loss is not None for s in stats)

    def test_manager_and_worker_checkpoints_round_trip_after_training(self, tmp_path):
        env = _build_env()
        hp = _tiny_hyperparams()
        manager_agent = build_manager_agent(k_max=K_MAX, hyperparams=hp, seed=3)
        worker_agent = build_worker_agent(k_max=K_MAX, p_max=P_MAX, hyperparams=hp, seed=3)
        run_training(env=env, manager_agent=manager_agent, worker_agent=worker_agent, episodes=10, seed=300)

        m_path = tmp_path / "manager.pt"
        w_path = tmp_path / "worker.pt"
        manager_agent.save_checkpoint(m_path)
        worker_agent.save_checkpoint(w_path)

        from app.training.agents.dqn_agent import MaskedDQNAgent

        loaded_manager = MaskedDQNAgent.load_checkpoint(m_path, hyperparams=hp)
        loaded_worker = MaskedDQNAgent.load_checkpoint(w_path, hyperparams=hp)

        obs = env.reset(seed=999)
        with torch.no_grad():
            x = torch.tensor([obs.vector], dtype=torch.float32)
            assert torch.allclose(manager_agent.online(x), loaded_manager.online(x))
        assert loaded_worker.input_dim == worker_agent.input_dim
        assert loaded_worker.output_dim == worker_agent.output_dim
