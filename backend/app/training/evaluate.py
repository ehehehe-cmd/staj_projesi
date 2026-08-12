"""Eğitilmiş checkpoint'i N sentetik test epizodunda greedy (keşifsiz)
çalıştırıp tamamlanma-oranı (completion rate) istatistiği basar —
TASARIM.md §4: "geliştirici sanity-check aracı; UI'da YOK".

TASARIM.md §14.1.C: `docs/RAPOR.md`'nin tek-seferlik `scratchpad/pool_*.py`
betiklerinin ürettiği trained-vs-random eşleştirilmiş (paired) karşılaştırma
metodolojisi buraya kalıcı bir `--baseline random` özelliği olarak taşındı —
yalnızca Manager rastgeleleştirilir (maskeye saygılı tekdüze seçim), Worker
HER İKİ kolda da aynı eğitilmiş/greedy ajandır (RAPOR.md §5'in "yalnızca
Manager değişkeni izole edildi" metodolojisiyle birebir aynı).

Kullanım:
    .venv/bin/python -m app.training.evaluate \\
        --manager-checkpoint model_registry/manager_20260805T120000Z.pt \\
        --worker-checkpoint model_registry/worker_20260805T120000Z.pt \\
        --episodes 100 --seed 999

    # trained (greedy manager) vs rastgele manager, eşleştirilmiş t-istatistiği:
    .venv/bin/python -m app.training.evaluate \\
        --manager-checkpoint model_registry/manager_20260807T101729Z.pt \\
        --worker-checkpoint model_registry/worker_20260807T101729Z.pt \\
        --episodes 200 --seed 999 --baseline random --courses-per-episode 60
"""

from __future__ import annotations

import argparse
import random
import statistics
from dataclasses import replace

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH as DEFAULT_SYNTHETIC_CONFIG_PATH
from app.data_generation.generator import SyntheticConfig, load_synthetic_config
from app.db.base import SessionLocal
from app.db.crud import load_constraint_config
from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent
from app.training.env import DecisionKind, HotRollingEnv
from app.training.train import DEFAULT_TRAIN_CONFIG_PATH, TrainingConfig, build_env, load_training_config


def run_episode_greedy(env: HotRollingEnv, manager_agent: MaskedDQNAgent, worker_agent: MaskedDQNAgent, *, seed: int) -> dict:
    obs = env.reset(seed=seed)
    result_info: dict = {}
    while obs is not None:
        if obs.kind is DecisionKind.MANAGER:
            action = manager_agent.select_action(obs.vector, obs.mask, greedy=True)
        else:
            action = worker_agent.select_action(obs.vector, obs.mask, greedy=True)
        result = env.step(action)
        result_info = result.info or result_info
        obs = result.next_observation
    return result_info


def run_episode_random_manager(env: HotRollingEnv, worker_agent: MaskedDQNAgent, *, seed: int, rng: random.Random) -> dict:
    """Manager: maskeye-saygılı tekdüze rastgele seçim. Worker: aynı eğitilmiş/greedy
    ajan — yalnızca Manager'ın karar kalitesini izole eder (bkz. modül docstring'i).
    """
    obs = env.reset(seed=seed)
    result_info: dict = {}
    while obs is not None:
        if obs.kind is DecisionKind.MANAGER:
            valid = [i for i, ok in enumerate(obs.mask) if ok]
            action = rng.choice(valid)
        else:
            action = worker_agent.select_action(obs.vector, obs.mask, greedy=True)
        result = env.step(action)
        result_info = result.info or result_info
        obs = result.next_observation
    return result_info


def course_completion_rate(info: dict, *, m_min: int) -> float:
    """Epizottaki kursların kaçının ``order_count >= m_min`` şartını sağladığı —
    canlı sistemin ``rolling_courses.status='completed'`` kriteriyle aynı (RAPOR.md §5).
    """
    counts = info.get("course_order_counts", {})
    if not counts:
        return 0.0
    completed = sum(1 for c in counts.values() if c >= m_min)
    return completed / len(counts)


def paired_t_statistic(a: list[float], b: list[float]) -> float:
    """Eşleştirilmiş (paired) t-istatistiği: mean(a-b) / (stdev(a-b)/sqrt(n)).

    RAPOR.md'nin kullandığı yöntemle aynı (dış bağımlılık gerektirmez).
    """
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("paired_t_statistic: en az 2 eşleştirilmiş eleman gerekir")
    diffs = [x - y for x, y in zip(a, b)]
    mean_diff = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    if sd == 0:
        return float("inf") if mean_diff != 0 else 0.0
    n = len(diffs)
    return mean_diff / (sd / (n**0.5))


def evaluate(
    *,
    cfg: TrainingConfig,
    synthetic_config: SyntheticConfig,
    constraints: RollingConstraints,
    manager_checkpoint: str,
    worker_checkpoint: str,
    episodes: int,
    seed: int,
) -> list[dict]:
    """Greedy (trained) politikayı ``episodes`` epizot çalıştırır; her epizot için
    ``{"coverage_ratio": ..., "completion_rate": ...}`` döndürür.
    """
    env = build_env(cfg, synthetic_config=synthetic_config, constraints=constraints)
    manager_agent = MaskedDQNAgent.load_checkpoint(manager_checkpoint, hyperparams=cfg.hyperparams)
    worker_agent = MaskedDQNAgent.load_checkpoint(worker_checkpoint, hyperparams=cfg.hyperparams)

    results: list[dict] = []
    for i in range(episodes):
        info = run_episode_greedy(env, manager_agent, worker_agent, seed=seed + i)
        results.append({
            "coverage_ratio": info.get("coverage_ratio", 0.0),
            "completion_rate": course_completion_rate(info, m_min=constraints.m_min),
        })
    return results


def compare_against_random(
    *,
    cfg: TrainingConfig,
    synthetic_config: SyntheticConfig,
    constraints: RollingConstraints,
    manager_checkpoint: str,
    worker_checkpoint: str,
    episodes: int,
    seed: int,
) -> dict:
    """Eşleştirilmiş (paired) trained-vs-random-manager karşılaştırması — RAPOR.md §5
    metodolojisi: aynı seed hem trained hem random kolunda AYNI sentetik havuzu üretir,
    yalnızca Manager'ın karar mekanizması değişir (Worker her iki kolda da eğitilmiş/greedy).
    """
    env = build_env(cfg, synthetic_config=synthetic_config, constraints=constraints)
    manager_agent = MaskedDQNAgent.load_checkpoint(manager_checkpoint, hyperparams=cfg.hyperparams)
    worker_agent = MaskedDQNAgent.load_checkpoint(worker_checkpoint, hyperparams=cfg.hyperparams)
    rng = random.Random(seed)

    trained_coverage, random_coverage = [], []
    trained_completion, random_completion = [], []
    for i in range(episodes):
        ep_seed = seed + i
        trained_info = run_episode_greedy(env, manager_agent, worker_agent, seed=ep_seed)
        random_info = run_episode_random_manager(env, worker_agent, seed=ep_seed, rng=rng)

        trained_coverage.append(trained_info.get("coverage_ratio", 0.0))
        random_coverage.append(random_info.get("coverage_ratio", 0.0))
        trained_completion.append(course_completion_rate(trained_info, m_min=constraints.m_min))
        random_completion.append(course_completion_rate(random_info, m_min=constraints.m_min))

    return {
        "trained_coverage": trained_coverage,
        "random_coverage": random_coverage,
        "trained_completion": trained_completion,
        "random_completion": random_completion,
        "coverage_t_stat": paired_t_statistic(trained_coverage, random_coverage),
        "completion_t_stat": paired_t_statistic(trained_completion, random_completion),
    }


def _print_summary(label: str, values: list[float]) -> None:
    print(f"{label}: ortalama={statistics.mean(values):.4f} std={statistics.stdev(values):.4f} "
          f"min={min(values):.4f} max={max(values):.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manager-checkpoint", type=str, required=True)
    parser.add_argument("--worker-checkpoint", type=str, required=True)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument("--config", type=str, default=str(DEFAULT_TRAIN_CONFIG_PATH))
    parser.add_argument("--synthetic-config", type=str, default=str(DEFAULT_SYNTHETIC_CONFIG_PATH))
    parser.add_argument(
        "--courses-per-episode", type=int, default=None,
        help="cfg.courses_per_episode'ı override eder (k_max/p_max sabit kalır — checkpoint mimarisiyle uyumlu kalması için)",
    )
    parser.add_argument(
        "--baseline", choices=["none", "random"], default="none",
        help="'random': maskeye-saygılı rastgele Manager'a karşı eşleştirilmiş (paired) karşılaştırma (RAPOR.md §5 metodolojisi)",
    )
    args = parser.parse_args()

    cfg = load_training_config(args.config)
    if args.courses_per_episode is not None:
        cfg = replace(cfg, courses_per_episode=args.courses_per_episode)
    synthetic_config = load_synthetic_config(args.synthetic_config)
    with SessionLocal() as session:
        constraints = load_constraint_config(session)

    if args.baseline == "none":
        results = evaluate(
            cfg=cfg, synthetic_config=synthetic_config, constraints=constraints,
            manager_checkpoint=args.manager_checkpoint, worker_checkpoint=args.worker_checkpoint,
            episodes=args.episodes, seed=args.seed,
        )
        print(f"N={len(results)} epizot (courses_per_episode={cfg.courses_per_episode})")
        _print_summary("coverage_ratio", [r["coverage_ratio"] for r in results])
        _print_summary("completion_rate", [r["completion_rate"] for r in results])
        return

    cmp_result = compare_against_random(
        cfg=cfg, synthetic_config=synthetic_config, constraints=constraints,
        manager_checkpoint=args.manager_checkpoint, worker_checkpoint=args.worker_checkpoint,
        episodes=args.episodes, seed=args.seed,
    )
    print(f"N={args.episodes} eşleştirilmiş epizot (courses_per_episode={cfg.courses_per_episode}, seed={args.seed})")
    print()
    print("-- coverage_ratio --")
    _print_summary("trained", cmp_result["trained_coverage"])
    _print_summary("random ", cmp_result["random_coverage"])
    print(f"t-istatistiği (trained-random, paired): {cmp_result['coverage_t_stat']:.3f}")
    print()
    print("-- kurs completion_rate --")
    _print_summary("trained", cmp_result["trained_completion"])
    _print_summary("random ", cmp_result["random_completion"])
    print(f"t-istatistiği (trained-random, paired): {cmp_result['completion_t_stat']:.3f}")


if __name__ == "__main__":
    main()
