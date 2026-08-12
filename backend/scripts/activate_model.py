"""Bir ``model_versions`` satırını aktif işaretler (TASARIM.md §1 ilke 5,
§6: "küçük bir admin script/SQL ile" — plandaki bu satırın karşılığı).

TASARIM.md'nin orijinal dosya listesinde YOKTU; Faz 4'te ``db/crud.py``'ye
eklenen ``activate_model_version`` için ince bir CLI sarmalayıcısı olarak
eklendi (bkz. TASARIM.md §12.5) — Faz 8'in "modeli aktif işaretle" adımını
elle SQL yazmadan yapabilmek için.

Kullanım:
    .venv/bin/python -m scripts.activate_model --list
    .venv/bin/python -m scripts.activate_model --id 3
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.db import crud
from app.db.base import SessionLocal
from app.db.models import ModelVersion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, default=None, help="aktif yapılacak model_versions.id")
    parser.add_argument("--list", action="store_true", help="mevcut model_versions satırlarını listele")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.list or args.id is None:
            rows = session.execute(
                select(ModelVersion).order_by(ModelVersion.level, ModelVersion.created_at.desc())
            ).scalars()
            for row in rows:
                marker = "*" if row.is_active else " "
                print(f"[{marker}] id={row.id} level={row.level} name={row.name} trained_at={row.trained_at}")
            if args.id is None:
                return

        deactivated = crud.activate_model_version(session, model_version_id=args.id)
        session.commit()
        print(f"model_versions.id={args.id} aktif yapıldı ({deactivated} eski kayıt pasifleştirildi)")


if __name__ == "__main__":
    main()
