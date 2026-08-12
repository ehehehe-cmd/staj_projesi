"""``WS /ws/live`` — TASARIM.md §4, §8.

Bağlantı kurulunca sunucu hiçbir şey GÖNDERMEZ (ilk state için frontend
``GET /api/courses/active`` çağırır, İlke 4) — bu route yalnızca client'ı
``ws.manager.ConnectionManager``'a kaydeder ve bağlantı canlı kaldığı
sürece (client'tan gelen herhangi bir mesajı sessizce yok sayarak, ör.
ping/pong) bekler; asıl veri akışı ``main.py``'nin lifespan görevinin
(``notifier.events()`` → ``manager.broadcast()``) tek yönlü push'udur.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    manager = websocket.app.state.connection_manager
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
