"""asyncpg ``LISTEN``/``NOTIFY`` → in-process asyncio broadcast köprüsü —
TASARIM.md §8: "``notifier.py``: asyncpg connection ile ``LISTEN
schedule_channel``; her NOTIFY geldiğinde ilgili ``live_events`` satırını
okuyup in-process bir asyncio ``Queue``/broadcast'e iletir."

Bu modül TEK sorumluluk taşır: kanalı dinlemek + payload'daki event id'ye
karşılık gelen ``live_events`` satırını okumak. Kimin bu olayları TÜKETTİĞİ
bu modülü ilgilendirmez — TASARIM.md §7 (``simulation_started/paused/
resumed/stopped/manual_step`` de ``live_events.event_type``'ın geçerli
değerleridir, bkz. ``db/models.py`` CHECK constraint) ile §8'i birlikte
okursak, İKİ farklı tüketici olduğu görülür:
  1) ``live_engine.py`` — kontrol komutlarını (pause/resume/stop/manual_step)
     düşük gecikmeyle almak için AYNI ``schedule_channel``'ı dinler.
  2) Faz 6'nın ``ws/manager.py``'si — frontend'e broadcast için.
İkisi de bu tek, jenerik sınıfı kullanır; kanal isimlendirmesi kasıtlı
olarak TEK'tir (İlke 3: API ve motor arasındaki tek gerçek-zamanlı bağ).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = "schedule_channel"


@dataclass(frozen=True, slots=True)
class LiveEventPayload:
    id: int
    event_type: str
    course_id: int | None
    payload: dict[str, Any]
    created_at: str


def _asyncpg_dsn(url: str | None = None) -> str:
    """``settings.database_url`` SQLAlchemy'nin ``postgresql+asyncpg://``
    şemasını kullanır; asyncpg'nin ``connect()``'i düz ``postgresql://``
    bekler."""
    raw = url if url is not None else settings.database_url
    return raw.replace("postgresql+asyncpg://", "postgresql://", 1)


class LiveEventNotifier:
    """``async with LiveEventNotifier() as notifier:`` şeklinde kullanılır;
    ``notifier.events()`` sonsuz bir async iterator, ``wait_for_event`` ise
    tek-seferlik (timeout destekli) bekleme sağlar — ``live_engine``'in
    "tick süresi kadar bekle AMA bir kontrol olayı gelirse erken uyan"
    yarışı için gereken budur.
    """

    def __init__(self, *, dsn: str | None = None, channel: str = DEFAULT_CHANNEL) -> None:
        self._dsn = dsn or _asyncpg_dsn()
        self._channel = channel
        self._conn: asyncpg.Connection | None = None
        self._queue: asyncio.Queue[int] = asyncio.Queue()

    async def __aenter__(self) -> "LiveEventNotifier":
        self._conn = await asyncpg.connect(self._dsn)
        await self._conn.add_listener(self._channel, self._on_notify)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._conn is not None:
            try:
                await self._conn.remove_listener(self._channel, self._on_notify)
            finally:
                await self._conn.close()
            self._conn = None

    def _on_notify(self, connection: object, pid: int, channel: str, payload: str) -> None:
        try:
            event_id = int(payload)
        except (TypeError, ValueError):
            logger.warning("%s: sayısal olmayan NOTIFY payload'ı görmezden gelindi: %r", self._channel, payload)
            return
        self._queue.put_nowait(event_id)

    async def wait_for_event(self, *, timeout: float | None = None) -> int | None:
        """Sıradaki event id'sini bekler; ``timeout`` saniye içinde hiçbir
        NOTIFY gelmezse ``None`` döner."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    async def fetch_event(self, event_id: int) -> LiveEventPayload | None:
        if self._conn is None:
            raise RuntimeError("LiveEventNotifier bağlı değil — 'async with' bloğu dışında çağrıldı")
        row = await self._conn.fetchrow(
            "SELECT id, event_type, course_id, payload, created_at FROM live_events WHERE id = $1", event_id
        )
        if row is None:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return LiveEventPayload(
            id=row["id"],
            event_type=row["event_type"],
            course_id=row["course_id"],
            payload=payload or {},
            created_at=row["created_at"].isoformat(),
        )

    async def events(self) -> AsyncIterator[LiveEventPayload]:
        """Sonsuz akış: her NOTIFY için karşılık gelen ``live_events``
        satırını çözüp verir (satır silinmiş/bulunamamışsa atlar)."""
        while True:
            event_id = await self.wait_for_event()
            if event_id is None:
                continue
            resolved = await self.fetch_event(event_id)
            if resolved is not None:
                yield resolved
