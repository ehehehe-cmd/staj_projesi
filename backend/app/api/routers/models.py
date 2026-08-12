"""``GET /api/models`` — TASARIM.md §4: "aktif manager/worker versiyon
bilgisi, salt okunur". "model-info" özelliğinin (§9: "karşılaştırma paneli
YOK") veri kaynağı — bilinçli olarak salt okunur, hiçbir POST/PUT/DELETE
YOKTUR (aktifleştirme ``scripts/activate_model.py`` ile elle yapılır,
TASARIM.md §6).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import ActiveModelsOut, ModelVersionOut
from app.db import crud
from app.db.models import ModelVersion

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=list[ModelVersionOut])
def list_models(
    level: str | None = Query(default=None, pattern="^(manager|worker)$"),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ModelVersion]:
    stmt = select(ModelVersion).order_by(ModelVersion.created_at.desc())
    if level is not None:
        stmt = stmt.where(ModelVersion.level == level)
    if is_active is not None:
        stmt = stmt.where(ModelVersion.is_active.is_(is_active))
    return list(db.execute(stmt.limit(limit)).scalars().all())


@router.get("/active", response_model=ActiveModelsOut)
def get_active_models(db: Session = Depends(get_db)) -> ActiveModelsOut:
    return ActiveModelsOut(
        manager=crud.get_active_model_version(db, level="manager"),
        worker=crud.get_active_model_version(db, level="worker"),
    )
