"""TASARIM.md §14.3.K doğrulama scripti — SONUCLAR.md §12.2/12.3 metodolojisiyle
BİREBİR aynı: aday KENDİ ortamında (kendi synthetic config + kendi m_max) aktif
baseline'a karşı eşleştirilmiş (paired) t-test ile test edilir, ardından aynı
ortamda maskeye-saygılı rastgele manager'a karşı kontrol edilir (worker
sabit/eğitilmiş — RAPOR.md §5 metodolojisi).

Sadece ``app.training.evaluate``'in ``evaluate``/``compare_against_random``/
``paired_t_statistic`` fonksiyonlarını iki checkpoint çifti üzerinde çalıştırıp
sonucu yan yana basar — yeni bir ölçüm mantığı icat etmez.

Kullanım (TASARIM.md §14.3.K Faz 1/Faz 2 doğrulaması için):
    cd backend && source .venv/bin/activate
    python -m scripts.compare_checkpoints \\
        --candidate-manager model_registry/manager_<ts>.pt \\
        --candidate-worker model_registry/worker_<ts>.pt \\
        --synthetic-config app/data_generation/config_synthetic_narrow_width_900_1200.yaml \\
        --m-max-override 120 --episodes 200 --seed 999 --label cap-only-v3
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics

from app.data_generation.generator import DEFAULT_CONFIG_PATH as DEFAULT_SYNTHETIC_CONFIG_PATH
from app.data_generation.generator import load_synthetic_config
from app.db.base import SessionLocal
from app.db.crud import load_constraint_config
from app.training.evaluate import compare_against_random, evaluate, paired_t_statistic
from app.training.train import DEFAULT_TRAIN_CONFIG_PATH, load_training_config

# Aktif baseline (id=790/791, cap-only-v3, 2026-08-16'da aktifleştirildi, m_max=120 migration'ıyla). Aktif model değişirse burası güncellenmeli.
BASELINE_MANAGER = "model_registry/manager_20260816T070142Z.pt"
BASELINE_WORKER = "model_registry/worker_20260816T070142Z.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate-manager", required=True)
    parser.add_argument("--candidate-worker", required=True)
    parser.add_argument("--synthetic-config", default=str(DEFAULT_SYNTHETIC_CONFIG_PATH))
    parser.add_argument("--m-max-override", type=int, default=None)
    parser.add_argument("--episodes", type=int, default=200)
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument("--label", default="candidate")
    args = parser.parse_args()

    cfg = load_training_config(str(DEFAULT_TRAIN_CONFIG_PATH))
    synthetic_config = load_synthetic_config(args.synthetic_config)
    with SessionLocal() as session:
        constraints = load_constraint_config(session)
    if args.m_max_override is not None:
        db_m_max = constraints.m_max
        constraints = dataclasses.replace(constraints, m_max=args.m_max_override)
        print(f"[info] m_max DB'den {db_m_max} okundu, {args.m_max_override} ile OVERRIDE edildi")

    print(f"=== {args.label} ortamında: baseline(aktif) vs {args.label} ===")
    print(f"synthetic_config={args.synthetic_config} m_max={constraints.m_max} episodes={args.episodes} seed={args.seed}")
    print()

    baseline_results = evaluate(
        cfg=cfg, synthetic_config=synthetic_config, constraints=constraints,
        manager_checkpoint=BASELINE_MANAGER, worker_checkpoint=BASELINE_WORKER,
        episodes=args.episodes, seed=args.seed,
    )
    candidate_results = evaluate(
        cfg=cfg, synthetic_config=synthetic_config, constraints=constraints,
        manager_checkpoint=args.candidate_manager, worker_checkpoint=args.candidate_worker,
        episodes=args.episodes, seed=args.seed,
    )

    base_cov = [r["coverage_ratio"] for r in baseline_results]
    cand_cov = [r["coverage_ratio"] for r in candidate_results]
    base_comp = [r["completion_rate"] for r in baseline_results]
    cand_comp = [r["completion_rate"] for r in candidate_results]

    cov_t = paired_t_statistic(cand_cov, base_cov)
    comp_t = paired_t_statistic(cand_comp, base_comp)

    print("-- coverage_ratio --")
    print(f"baseline(aktif): ort={statistics.mean(base_cov):.4f}")
    print(f"{args.label}: ort={statistics.mean(cand_cov):.4f}")
    print(f"t-istatistiği (candidate-baseline, paired): {cov_t:.3f}")
    print()
    print("-- completion_rate --")
    print(f"baseline(aktif): ort={statistics.mean(base_comp):.4f}")
    print(f"{args.label}: ort={statistics.mean(cand_comp):.4f}")
    print(f"t-istatistiği (candidate-baseline, paired): {comp_t:.3f}")
    print()

    print(f"=== {args.label} ortamında: {args.label} vs rastgele manager (worker sabit) ===")
    rand_result = compare_against_random(
        cfg=cfg, synthetic_config=synthetic_config, constraints=constraints,
        manager_checkpoint=args.candidate_manager, worker_checkpoint=args.candidate_worker,
        episodes=args.episodes, seed=args.seed,
    )
    print(f"trained cov ort={statistics.mean(rand_result['trained_coverage']):.4f} "
          f"random cov ort={statistics.mean(rand_result['random_coverage']):.4f} "
          f"t={rand_result['coverage_t_stat']:.3f}")
    print(f"trained comp ort={statistics.mean(rand_result['trained_completion']):.4f} "
          f"random comp ort={statistics.mean(rand_result['random_completion']):.4f} "
          f"t={rand_result['completion_t_stat']:.3f}")


if __name__ == "__main__":
    main()
