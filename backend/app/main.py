"""FastAPI app + startup: DB pool, LISTEN task başlat — TASARIM.md §4, §8.

Çalıştırma: ``uvicorn app.main:app`` (TASARIM.md §2 "Üç bağımsız çalışma
zamanı"nın ikincisi — ``python -m app.simulation.live_engine`` AYRI bir
süreç olarak paralel çalışır, İlke 3).

Lifespan görevi TEK bir şey yapar: ``notifier.py``'nin ``schedule_channel``
LISTEN'ini açar ve gelen her olayı ``ws/manager.py``'nin bağlı
WebSocket'lerine JSON olarak yayınlar. "DB pool" için ayrı bir kurulum
GEREKMEZ — ``db/base.py``'deki ``engine``/``async_engine`` singleton'ları
zaten import anında oluşturulur (SQLAlchemy'nin kendi connection pool'u).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import courses, decisions, models, orders, simulation, ws_routes
from app.simulation.notifier import LiveEventNotifier
from app.simulation.order_stream import OrderStreamController
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)


async def _broadcast_events(notifier: LiveEventNotifier, manager: ConnectionManager) -> None:
    async for event in notifier.events():
        await manager.broadcast(
            {
                "id": event.id,
                "event_type": event.event_type,
                "course_id": event.course_id,
                "payload": event.payload,
                "created_at": event.created_at,
            }
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.connection_manager = ConnectionManager()
    app.state.order_stream = OrderStreamController()
    async with LiveEventNotifier() as notifier:
        broadcast_task = asyncio.create_task(_broadcast_events(notifier, app.state.connection_manager))
        try:
            yield
        finally:
            await app.state.order_stream.stop()
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Sıcak Haddeleme HRL Çizelgeleme API",
    description="TASARIM.md §4/§7/§8 — canlı çizelgeleme sisteminin REST + WebSocket katmanı.",
    lifespan=lifespan,
)

# Tek-operatörlük bir demo/izleme sistemi (TASARIM.md §0.2: auth/çoklu
# kullanıcı bilinçli olarak kapsam dışı) — CORS bu yüzden geliştirme
# kolaylığı için izin verici tutuldu (Angular dev server farklı porttan
# konuşur). Üretimde sıkılaştırmak isteyen bir operatör bunu değiştirebilir.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)
app.include_router(courses.router)
app.include_router(decisions.router)
app.include_router(models.router)
app.include_router(simulation.router)
app.include_router(ws_routes.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}
