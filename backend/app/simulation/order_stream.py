"""API sürecinde çalışan, dashboard'dan aç/kapat edilebilen EŞİK-TABANLI
otomatik order doldurma — TASARIM.md §9 eki (2026-08-17).

İlk sürüm sabit aralıklı bir zamanlayıcıydı (``interval_s``'de bir parti
ekle) — kullanıcı geri bildirimi: "20 saniyede bir ekliyor ama bu çok az,
sistem kendini döndüremiyor" (havuz tüketimi TALEBE göre değişken, sabit
bir zamanlayıcı ya çok yavaş ya gereksiz kalıyor). Bu yüzden mantık
DEĞİŞTİRİLDİ: kullanıcı bir HEDEF (``target_main_slabs``) girer, arka plan
görevi kısa aralıklarla (``_CHECK_INTERVAL_S``) havuzu yoklar, hedefin
altındaysa hedefe ULAŞANA KADAR art arda parti ekler — talebe duyarlı.

``live_engine.py::background_order_generator`` ile AYNI üretim kod yolunu
(``generate_batch`` + ``crud.insert_generated_batch``) kullanır.
"""

from __future__ import annotations

import asyncio
import logging
import random

from app.core.constraints import RollingConstraints
from app.data_generation.generator import SyntheticConfig, generate_batch
from app.db import crud
from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

# Havuzun ne sıklıkla yoklanacağı — kullanıcıya açık bir parametre DEĞİL
# (arayüzü karmaşıklaştırmaz), yeterince kısa ki hızlı tüketimde bile
# havuz uzun süre boş kalmasın.
_CHECK_INTERVAL_S = 3.0
# Tek bir yoklamada eklenebilecek azami parti sayısı — hedef çok yüksek
# girilirse (ya da generate_batch beklenenden küçük partiler üretirse)
# sonsuz/aşırı üretimi önleyen güvenlik sınırı.
_MAX_BATCHES_PER_CHECK = 25


class OrderStreamController:
    """Tek bir arka plan görevini yönetir — aynı anda en fazla 1 akış olabilir
    (tek-operatörlük varsayımıyla tutarlı, bkz. TASARIM.md §0.2)."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._target_main_slabs: int | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def target_main_slabs(self) -> int | None:
        return self._target_main_slabs if self.running else None

    def start(
        self,
        *,
        synthetic_config: SyntheticConfig,
        constraints: RollingConstraints,
        target_main_slabs: int,
        seed: int | None,
    ) -> None:
        if self.running:
            return
        self._target_main_slabs = target_main_slabs
        rng = random.Random(seed)

        async def _loop() -> None:
            try:
                while True:
                    added = await asyncio.to_thread(_top_up_if_needed, synthetic_config, constraints, rng, target_main_slabs)
                    if added:
                        logger.info("order stream: hedefe (%d) ulaşmak için %d parti eklendi", target_main_slabs, added)
                    await asyncio.sleep(_CHECK_INTERVAL_S)
            except asyncio.CancelledError:
                pass

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._target_main_slabs = None


def _top_up_if_needed(
    synthetic_config: SyntheticConfig, constraints: RollingConstraints, rng: random.Random, target_main_slabs: int
) -> int:
    """Havuz ``target_main_slabs``'ın altındaysa hedefe ulaşana (ya da
    güvenlik sınırına) kadar parti ekler; hiçbir şey eklenmezse 0 döner."""
    added_batches = 0
    with SessionLocal() as session:
        while added_batches < _MAX_BATCHES_PER_CHECK:
            status = crud.get_pool_status(session)
            if status["remaining_main_slabs"] >= target_main_slabs:
                break
            batch = generate_batch(synthetic_config, constraints, rng)
            crud.insert_generated_batch(session, batch)
            # SessionLocal `autoflush=False` ile kurulu (bkz. db/base.py) —
            # flush OLMADAN bir sonraki `get_pool_status` az önce eklenen
            # satırları GÖRMEZ, döngü ihtiyaçtan fazla parti ekler.
            session.flush()
            added_batches += 1
        if added_batches:
            crud.emit_event(
                session,
                event_type="order_generated",
                payload={"batches": added_batches, "target_main_slabs": target_main_slabs},
            )
            session.commit()
    return added_batches
