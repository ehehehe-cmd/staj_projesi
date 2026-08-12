"""Mevcut pending order havuzunu temizler + generator.py ile yeni sentetik
parti(ler) ekler (TASARIM.md §4, §12.4).

Kullanım:
    .venv/bin/python -m scripts.seed_db --seed 7 --batches 1
    .venv/bin/python -m scripts.seed_db --seed 7 --batches 3 --no-clear
"""

from __future__ import annotations

import argparse
import random

from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.base import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="rastgelelik tohumu (verilmezse rastgele)")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_PATH), help="config_synthetic.yaml yolu")
    parser.add_argument("--batches", type=int, default=1, help="kaç sentetik parti (generate_batch çağrısı) üretilecek")
    parser.add_argument(
        "--no-clear", action="store_true", help="mevcut pending order/grup havuzunu temizleme, üzerine ekle"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    config = load_synthetic_config(args.config)

    with SessionLocal() as session:
        constraints = crud.load_constraint_config(session)

        if not args.no_clear:
            deleted_orders, deleted_groups = crud.clear_pending_pool(session)
            print(f"temizlendi: {deleted_orders} order, {deleted_groups} grup")

        total_orders = 0
        for i in range(args.batches):
            batch = generate_batch(config, constraints, rng)
            inserted = crud.insert_generated_batch(session, batch)
            total_orders += inserted
            print(f"parti {i + 1}/{args.batches}: {inserted} order ({len(batch.main_groups)} ana grup, {len(batch.transitions)} geçiş order)")

        session.commit()
        print(f"tamamlandı: toplam {total_orders} order eklendi")


if __name__ == "__main__":
    main()
