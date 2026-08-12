"""FastAPI ``Depends`` yardımcıları — TASARIM.md §4, §12.7.

Route handler'lar kasıtlı olarak SENKRON (``def``, ``async def`` DEĞİL)
yazılır: proje genelinde DB katmanı zaten senkron SQLAlchemy'dir
(``db/crud.py``, ``simulation/control.py``) — FastAPI senkron route'ları
otomatik olarak bir threadpool'da çalıştırır (Starlette'in yerleşik
davranışı), bu yüzden ayrı bir async DB katmanı YAZMAK (İlke 8: basitlik
önceliği) bu ölçekte gereksiz bir karmaşıklık olurdu. Yalnızca WebSocket
route'u (``ws_routes.py``) doğası gereği ``async def``'tir.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.db.base import SessionLocal


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
