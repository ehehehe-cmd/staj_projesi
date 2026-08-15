"""TASARIM.md §14.3.J/K'nin izole karşılaştırma turları için eğitim wrapper'ı.

``app.training.train``'in ``main()``'iyle BİREBİR aynı davranır, TEK farkla:
``constraint_config``'i DB'den okuduktan sonra ``m_max``'ı bellek-içinde
override eder (DB'ye HİÇ YAZMAZ, paylaşılan/canlı sistemi etkilemez) —
böylece ``m_max=120`` gerektiren izole eğitim turları, gerçek migration
(``alembic/versions/0127bbb2a79c_...``) UYGULANMADAN (canlı sistem hâlâ
``m_max=100`` görürken) test edilebilir.

``m_max`` DB'de hâlâ değişmediyse (``constraint_config.m_max == 100``) ve
override 100'e eşitse bu script ``app.training.train`` ile TAMAMEN aynı
sonucu üretir — yani "width-only" turu için de (override=100 verilerek)
kullanılabilir, zorunlu değildir (doğrudan ``python -m app.training.train``
de eşdeğerdir).

Kalıcı bir CLI bayrağı olarak ``train.py``'ye EKLENMEDİ — ``m_max`` §1 ilke 6
gereği config-driven/DB-driven bir kısıttır, ikinci bir "kaynak" (CLI
override) eklemek bu ilkeyi ihlal eder; bu script yalnızca migration
UYGULANMADAN ÖNCEki izole deney/karşılaştırma dönemi için bir köprüdür —
migration uygulandığında (m_max DB'de kalıcı olarak 120 olduğunda) bu
script'in ARTIK GEREĞİ KALMAZ, silinebilir.

Kullanım (TASARIM.md §14.3.K'daki "nihai model" planının 2. adımı):
    cd backend && source .venv/bin/activate
    python -m scripts.train_with_constraint_override \\
        --episodes 16000 --seed 7 --m-max-override 120 \\
        --synthetic-config app/data_generation/config_synthetic_narrow_width_900_1200.yaml \\
        --tensorboard-dir runs/cap_only_v2 \\
        --notes "..."
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import logging
from pathlib import Path

from torch.utils.tensorboard import SummaryWriter

from app.core.config import settings
from app.data_generation.generator import DEFAULT_CONFIG_PATH as DEFAULT_SYNTHETIC_CONFIG_PATH
from app.data_generation.generator import load_synthetic_config
from app.db.base import SessionLocal
from app.db.crud import load_constraint_config, record_model_version, record_training_run
from app.training.agents.manager_dqn import build_manager_agent
from app.training.agents.worker_dqn import build_worker_agent
from app.training.train import (
    DEFAULT_TRAIN_CONFIG_PATH,
    EpisodeStats,
    build_env,
    load_training_config,
    run_training,
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--config", type=str, default=str(DEFAULT_TRAIN_CONFIG_PATH))
    parser.add_argument("--synthetic-config", type=str, default=str(DEFAULT_SYNTHETIC_CONFIG_PATH))
    parser.add_argument("--tensorboard-dir", type=str, default="runs")
    parser.add_argument("--notes", type=str, default="")
    parser.add_argument("--m-max-override", type=int, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_training_config(args.config)
    episodes = args.episodes if args.episodes is not None else cfg.episodes
    seed = args.seed if args.seed is not None else cfg.seed
    synthetic_config = load_synthetic_config(args.synthetic_config)

    with SessionLocal() as session:
        constraints = load_constraint_config(session)
    db_m_max = constraints.m_max
    constraints = dataclasses.replace(constraints, m_max=args.m_max_override)
    logger.info("m_max DB'den %d okundu, %d ile OVERRIDE edildi (DB'ye yazılmadı)", db_m_max, args.m_max_override)

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
        "m_max_override": args.m_max_override,
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
            session, started_at=started_at, ended_at=ended_at, seed=seed,
            episodes=episodes, hyperparams=hyperparams_dict, notes=args.notes,
        )
        record_model_version(
            session, level="manager", name=f"manager_{timestamp}",
            checkpoint_path=str(manager_path), trained_at=ended_at,
            training_run_id=training_run_id,
            hyperparams={**hyperparams_dict, "architecture": manager_arch},
            metrics={"tail_avg_manager_reward": tail_avg_manager},
        )
        record_model_version(
            session, level="worker", name=f"worker_{timestamp}",
            checkpoint_path=str(worker_path), trained_at=ended_at,
            training_run_id=training_run_id,
            hyperparams={**hyperparams_dict, "architecture": worker_arch},
            metrics={},
        )
        session.commit()
    logger.info(
        "training_runs.id=%d, model_versions kaydedildi (is_active=false). "
        "id çifti için: SELECT id,level FROM model_versions WHERE training_run_id=%d",
        training_run_id, training_run_id,
    )


if __name__ == "__main__":
    main()
