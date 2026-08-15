"""Offline eğitim CLI — TASARIM.md §4, §6:

    python -m app.training.train --episodes 3000 --seed 7

Bu modül DB'ye hiç dokunmadan (§1 ilke 2) epizotları çalıştırır; TEK DB
etkileşimi eğitim TAMAMEN bittikten sonra, checkpoint + ``training_runs`` +
``model_versions`` satırlarının TEK SEFERLİK yazımıdır (§6, §3.10) —
``--no-db`` ile bu adım tamamen atlanabilir (ör. hızlı smoke-test'lerde).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from torch.utils.tensorboard import SummaryWriter

from app.core.config import settings
from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH as DEFAULT_SYNTHETIC_CONFIG_PATH
from app.data_generation.generator import SyntheticConfig, load_synthetic_config
from app.db.base import SessionLocal
from app.db.crud import load_constraint_config, record_model_version, record_training_run
from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent
from app.training.env import DecisionKind, HotRollingEnv, RewardWeights

logger = logging.getLogger(__name__)

DEFAULT_TRAIN_CONFIG_PATH = Path(__file__).parent / "configs" / "default.yaml"


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    seed: int
    episodes: int
    courses_per_episode: int
    k_max: int
    p_max: int
    max_manager_steps_per_course: int
    max_worker_steps_per_subtask: int
    hyperparams: DQNHyperparams
    reward_weights: RewardWeights

    @classmethod
    def from_mapping(cls, values: dict) -> "TrainingConfig":
        rw = values["reward_weights"]
        hp = DQNHyperparams(
            hidden_dim=int(values["hidden_dim"]),
            learning_rate=float(values["learning_rate"]),
            gamma=float(values["gamma"]),
            batch_size=int(values["batch_size"]),
            target_update_interval=int(values["target_update_interval"]),
            replay_capacity=int(values["replay_capacity"]),
            min_replay_size=int(values["min_replay_size"]),
            epsilon_start=float(values["epsilon_start"]),
            epsilon_end=float(values["epsilon_end"]),
            epsilon_decay_steps=int(values["epsilon_decay_steps"]),
        )
        return cls(
            seed=int(values["seed"]),
            episodes=int(values["episodes"]),
            courses_per_episode=int(values["courses_per_episode"]),
            k_max=int(values["k_max"]),
            p_max=int(values["p_max"]),
            max_manager_steps_per_course=int(values["max_manager_steps_per_course"]),
            max_worker_steps_per_subtask=int(values["max_worker_steps_per_subtask"]),
            hyperparams=hp,
            reward_weights=RewardWeights(
                omega1=float(rw["omega1"]),
                omega2=float(rw["omega2"]),
                r_s=float(rw["r_s"]),
                beta0=float(rw["beta0"]),
                beta1=float(rw["beta1"]),
                beta2=float(rw["beta2"]),
                m_target=float(rw["m_target"]),
                omega3=float(rw["omega3"]),
            ),
        )


def load_training_config(path: str | Path = DEFAULT_TRAIN_CONFIG_PATH) -> TrainingConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TrainingConfig.from_mapping(raw)


def build_env(
    cfg: TrainingConfig,
    *,
    synthetic_config: SyntheticConfig,
    constraints: RollingConstraints,
) -> HotRollingEnv:
    return HotRollingEnv(
        synthetic_config=synthetic_config,
        constraints=constraints,
        reward_weights=cfg.reward_weights,
        courses_per_episode=cfg.courses_per_episode,
        k_max=cfg.k_max,
        p_max=cfg.p_max,
        max_manager_steps_per_course=cfg.max_manager_steps_per_course,
        max_worker_steps_per_subtask=cfg.max_worker_steps_per_subtask,
    )


@dataclass(frozen=True, slots=True)
class EpisodeStats:
    episode: int
    manager_return: float
    worker_subtask_returns: list[float]
    worker_success_count: int
    worker_failure_count: int
    coverage_ratio: float
    manager_loss: float | None
    worker_loss: float | None
    # TASARIM.md §14.1.B tanı sinyalleri (worker/loss kararsızlığı araştırması):
    manager_grad_norm: float | None
    worker_grad_norm: float | None
    worker_reward_batch_std: float | None


def run_training(
    *,
    env: HotRollingEnv,
    manager_agent: MaskedDQNAgent,
    worker_agent: MaskedDQNAgent,
    episodes: int,
    seed: int,
    on_episode_end: Callable[[EpisodeStats], None] | None = None,
) -> list[EpisodeStats]:
    """Ana eğitim döngüsü — TASARIM.md §12.5 karar #7/#8'deki semi-MDP
    ödül-ilişkilendirme protokolünü uygular. DB/dosya I/O YAPMAZ (saf);
    çağıran (``main()``) sonuçları kalıcılaştırır.
    """
    all_stats: list[EpisodeStats] = []

    for ep in range(episodes):
        obs = env.reset(seed=seed + ep)
        pending_manager: tuple[list[float], list[bool], int] | None = None
        pending_worker: tuple[list[float], list[bool], int] | None = None

        manager_return = 0.0
        worker_subtask_returns: list[float] = []
        current_worker_return = 0.0
        worker_success = 0
        worker_failure = 0
        last_manager_loss: float | None = None
        last_worker_loss: float | None = None
        last_manager_grad_norm: float | None = None
        last_worker_grad_norm: float | None = None
        last_worker_reward_batch_std: float | None = None
        last_result_info: dict = {}

        while obs is not None:
            if obs.kind is DecisionKind.MANAGER:
                action = manager_agent.select_action(obs.vector, obs.mask)
                pending_manager = (obs.vector, obs.mask, action)
            else:
                action = worker_agent.select_action(obs.vector, obs.mask)
                pending_worker = (obs.vector, obs.mask, action)

            result = env.step(action)
            last_result_info = result.info or last_result_info
            next_obs = result.next_observation

            for t in result.transitions:
                # bkz. env.Transition docstring: done=False iken next_observation
                # HER ZAMAN result.next_observation ile aynı ajana aittir.
                nv = next_obs.vector if (not t.done and next_obs is not None) else None
                nm = next_obs.mask if (not t.done and next_obs is not None) else None
                if t.kind is DecisionKind.MANAGER:
                    assert pending_manager is not None
                    v, m, a = pending_manager
                    pending_manager = None
                    manager_agent.store(v, m, a, t.reward, nv, nm, t.done)
                    manager_return += t.reward
                else:
                    assert pending_worker is not None
                    v, m, a = pending_worker
                    pending_worker = None
                    worker_agent.store(v, m, a, t.reward, nv, nm, t.done)
                    current_worker_return += t.reward
                    if t.done:
                        worker_subtask_returns.append(current_worker_return)
                        if t.reward > 0:
                            worker_success += 1
                        else:
                            worker_failure += 1
                        current_worker_return = 0.0

            m_loss = manager_agent.train_step()
            w_loss = worker_agent.train_step()
            if m_loss is not None:
                last_manager_loss = m_loss
                last_manager_grad_norm = manager_agent.last_grad_norm
            if w_loss is not None:
                last_worker_loss = w_loss
                last_worker_grad_norm = worker_agent.last_grad_norm
                last_worker_reward_batch_std = worker_agent.last_reward_batch_std

            obs = next_obs

        stats = EpisodeStats(
            episode=ep,
            manager_return=manager_return,
            worker_subtask_returns=worker_subtask_returns,
            worker_success_count=worker_success,
            worker_failure_count=worker_failure,
            coverage_ratio=last_result_info.get("coverage_ratio", 0.0),
            manager_loss=last_manager_loss,
            worker_loss=last_worker_loss,
            manager_grad_norm=last_manager_grad_norm,
            worker_grad_norm=last_worker_grad_norm,
            worker_reward_batch_std=last_worker_reward_batch_std,
        )
        all_stats.append(stats)
        if on_episode_end is not None:
            on_episode_end(stats)

    return all_stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline HRL eğitim CLI (TASARIM.md §6)")
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--config", type=str, default=str(DEFAULT_TRAIN_CONFIG_PATH))
    parser.add_argument("--synthetic-config", type=str, default=str(DEFAULT_SYNTHETIC_CONFIG_PATH))
    parser.add_argument("--tensorboard-dir", type=str, default="runs")
    parser.add_argument("--no-db", action="store_true", help="training_runs/model_versions kaydını atla")
    parser.add_argument("--notes", type=str, default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_training_config(args.config)
    episodes = args.episodes if args.episodes is not None else cfg.episodes
    seed = args.seed if args.seed is not None else cfg.seed
    synthetic_config = load_synthetic_config(args.synthetic_config)

    with SessionLocal() as session:
        constraints = load_constraint_config(session)

    env = build_env(cfg, synthetic_config=synthetic_config, constraints=constraints)
    manager_agent = build_manager_agent(k_max=cfg.k_max, hyperparams=cfg.hyperparams, seed=seed)
    worker_agent = build_worker_agent(k_max=cfg.k_max, p_max=cfg.p_max, hyperparams=cfg.hyperparams, seed=seed)

    writer = SummaryWriter(log_dir=args.tensorboard_dir)

    def on_episode_end(stats: EpisodeStats) -> None:
        writer.add_scalar("manager/episode_reward", stats.manager_return, stats.episode)
        writer.add_scalar("manager/coverage_ratio", stats.coverage_ratio, stats.episode)
        if stats.worker_subtask_returns:
            avg_worker = sum(stats.worker_subtask_returns) / len(stats.worker_subtask_returns)
            writer.add_scalar("worker/avg_subtask_reward", avg_worker, stats.episode)
        writer.add_scalar("worker/success_count", stats.worker_success_count, stats.episode)
        writer.add_scalar("worker/failure_count", stats.worker_failure_count, stats.episode)
        subtask_total = stats.worker_success_count + stats.worker_failure_count
        if subtask_total > 0:
            writer.add_scalar("worker/success_ratio", stats.worker_success_count / subtask_total, stats.episode)
        if stats.manager_loss is not None:
            writer.add_scalar("manager/loss", stats.manager_loss, stats.episode)
        if stats.worker_loss is not None:
            writer.add_scalar("worker/loss", stats.worker_loss, stats.episode)
        # TASARIM.md §14.1.B tanı sinyalleri:
        if stats.manager_grad_norm is not None:
            writer.add_scalar("manager/grad_norm", stats.manager_grad_norm, stats.episode)
        if stats.worker_grad_norm is not None:
            writer.add_scalar("worker/grad_norm", stats.worker_grad_norm, stats.episode)
        if stats.worker_reward_batch_std is not None:
            writer.add_scalar("worker/reward_batch_std", stats.worker_reward_batch_std, stats.episode)
        if stats.episode % 50 == 0:
            logger.info(
                "episode=%d manager_return=%.4f coverage=%.3f worker_subtasks=%d (success=%d, fail=%d)",
                stats.episode, stats.manager_return, stats.coverage_ratio,
                len(stats.worker_subtask_returns), stats.worker_success_count, stats.worker_failure_count,
            )

    started_at = dt.datetime.now(dt.timezone.utc)
    all_stats = run_training(
        env=env, manager_agent=manager_agent, worker_agent=worker_agent,
        episodes=episodes, seed=seed, on_episode_end=on_episode_end,
    )
    ended_at = dt.datetime.now(dt.timezone.utc)
    writer.close()

    tail = all_stats[-min(50, len(all_stats)):]
    tail_avg_manager = sum(s.manager_return for s in tail) / len(tail)
    logger.info("Eğitim bitti. Son %d epizot manager ortalama ödülü: %.4f", len(tail), tail_avg_manager)

    if args.no_db:
        return

    registry_dir = Path(settings.model_registry_path)
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    manager_path = registry_dir / f"manager_{timestamp}.pt"
    worker_path = registry_dir / f"worker_{timestamp}.pt"
    manager_arch = manager_agent.save_checkpoint(manager_path)
    worker_arch = worker_agent.save_checkpoint(worker_path)

    hyperparams_dict = {
        "hidden_dim": cfg.hyperparams.hidden_dim,
        "learning_rate": cfg.hyperparams.learning_rate,
        "gamma": cfg.hyperparams.gamma,
        "batch_size": cfg.hyperparams.batch_size,
        "target_update_interval": cfg.hyperparams.target_update_interval,
        "replay_capacity": cfg.hyperparams.replay_capacity,
        "min_replay_size": cfg.hyperparams.min_replay_size,
        "epsilon_start": cfg.hyperparams.epsilon_start,
        "epsilon_end": cfg.hyperparams.epsilon_end,
        "epsilon_decay_steps": cfg.hyperparams.epsilon_decay_steps,
        "k_max": cfg.k_max,
        "p_max": cfg.p_max,
        "courses_per_episode": cfg.courses_per_episode,
        "reward_weights": {
            "omega1": cfg.reward_weights.omega1,
            "omega2": cfg.reward_weights.omega2,
            "r_s": cfg.reward_weights.r_s,
            "beta0": cfg.reward_weights.beta0,
            "beta1": cfg.reward_weights.beta1,
            "beta2": cfg.reward_weights.beta2,
            "m_target": cfg.reward_weights.m_target,
            "omega3": cfg.reward_weights.omega3,
        },
    }

    with SessionLocal() as session:
        training_run_id = record_training_run(
            session,
            started_at=started_at,
            ended_at=ended_at,
            seed=seed,
            episodes=episodes,
            hyperparams=hyperparams_dict,
            notes=args.notes,
        )
        record_model_version(
            session,
            level="manager",
            name=f"manager_{timestamp}",
            checkpoint_path=str(manager_path),
            trained_at=ended_at,
            training_run_id=training_run_id,
            hyperparams={**hyperparams_dict, "architecture": manager_arch},
            metrics={"tail_avg_manager_reward": tail_avg_manager},
        )
        record_model_version(
            session,
            level="worker",
            name=f"worker_{timestamp}",
            checkpoint_path=str(worker_path),
            trained_at=ended_at,
            training_run_id=training_run_id,
            hyperparams={**hyperparams_dict, "architecture": worker_arch},
            metrics={},
        )
        session.commit()
    logger.info("training_runs/model_versions kaydedildi (is_active=false). Aktifleştirmek için "
                "scripts/activate_model.py kullanılabilir.")


if __name__ == "__main__":
    main()
