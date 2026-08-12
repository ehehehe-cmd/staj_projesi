"""WebSocket connection manager — TASARIM.md §4, §8: "bağlı WebSocket
client'lara [notifier'dan gelen] payload'ı JSON olarak broadcast eder."

Bu sınıf ``notifier.py``'den TAMAMEN bağımsızdır (tek sorumluluk: bağlı
soketlerin defterini tutmak + hepsine aynı JSON'u göndermek) — köprüleme
(notifier olayı → broadcast çağrısı) ``main.py``'nin lifespan görevidir.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict) -> None:
        """Bağlı TÜM soketlere aynı JSON payload'ı gönderir; gönderim
        sırasında kopan bir soket varsa sessizce defterden düşürülür (bir
        client'ın disconnect'i diğerlerinin broadcast'ini bozmamalı)."""
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    def connection_count(self) -> int:
        return len(self._connections)
