"""``GET /api/decisions`` — TASARIM.md §4: "manager+worker log, filtrelenebilir/
sayfalanabilir". "decision-log" özelliğinin (§9) veri kaynağı.

Manager ve worker kararları TEK, zaman-sıralı bir akışta birleştirilir
(``kind`` ayırt edici alanıyla) — ``since`` parametresi İlke 4'ün ("Bağlantı
koptuğunda kaçırılan olaylar created_at zaman damgasına göre REST ile
tamamlanır") decision-log özelinde uygulanışıdır: WS bağlantısı koparsa,
frontend ``GET /api/decisions?since=<son_bilinen decided_at>`` ile
kaçırdığı kararları tamamlar (§8). Genel "her olay tipini yeniden oynat"
ihtiyacı ``GET /api/courses/active``'in taze bir snapshot sağlamasıyla
zaten karşılanıyor (bkz. TASARIM.md §12.7 karar notu) — bu yüzden ayrı bir
events.py router'ı YOKTUR.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import DecisionsPage, ManagerDecisionOut, WorkerDecisionOut
from app.db.models import ManagerDecision, WorkerDecision

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("", response_model=DecisionsPage)
def list_decisions(
    kind: str | None = Query(default=None, pattern="^(manager|worker)$"),
    course_id: int | None = Query(default=None),
    since: dt.datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> DecisionsPage:
    items: list[ManagerDecisionOut | WorkerDecisionOut] = []

    if kind in (None, "manager"):
        stmt = select(ManagerDecision).order_by(ManagerDecision.decided_at)
        if course_id is not None:
            stmt = stmt.where(ManagerDecision.course_id == course_id)
        if since is not None:
            stmt = stmt.where(ManagerDecision.decided_at > since)
        rows = db.execute(stmt.limit(limit)).scalars().all()
        items.extend(ManagerDecisionOut.model_validate(r) for r in rows)

    if kind in (None, "worker"):
        stmt = select(WorkerDecision).order_by(WorkerDecision.decided_at)
        if course_id is not None:
            stmt = stmt.where(WorkerDecision.course_id == course_id)
        if since is not None:
            stmt = stmt.where(WorkerDecision.decided_at > since)
        rows = db.execute(stmt.limit(limit)).scalars().all()
        items.extend(WorkerDecisionOut.model_validate(r) for r in rows)

    items.sort(key=lambda item: item.decided_at)
    items = items[:limit]
    next_since = items[-1].decided_at if items else since

    return DecisionsPage(items=items, next_since=next_since)
