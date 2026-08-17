"""``GET /api/orders``, ``GET /api/orders/groups``, ``POST /api/orders/generate``
— TASARIM.md §4. "order-pool" özelliğinin (§9: "bekleyen ana gruplar + geçiş
order havuzu, filtrelenebilir liste") veri kaynağı.
"""

from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    GenerateOrdersRequest,
    GenerateOrdersResponse,
    MainGroupOut,
    OrderStreamStartRequest,
    OrderStreamStatusOut,
    PoolStatusOut,
    ResetForDemoRequest,
    ResetForDemoResponse,
    SlabOrderOut,
)
from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.crud import load_constraint_config
from app.db.models import MainProductGroup, SlabOrder
from app.simulation import control

router = APIRouter(prefix="/api/orders", tags=["orders"])

_synthetic_config = load_synthetic_config(DEFAULT_CONFIG_PATH)


@router.get("", response_model=list[SlabOrderOut])
def list_orders(
    status: str | None = Query(default=None),
    order_class: str | None = Query(default=None),
    main_group_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[SlabOrder]:
    stmt = select(SlabOrder).order_by(SlabOrder.id.desc())
    if status is not None:
        stmt = stmt.where(SlabOrder.status == status)
    if order_class is not None:
        stmt = stmt.where(SlabOrder.order_class == order_class)
    if main_group_id is not None:
        stmt = stmt.where(SlabOrder.main_group_id == main_group_id)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get("/groups", response_model=list[MainGroupOut])
def list_main_groups(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MainProductGroup]:
    stmt = select(MainProductGroup).order_by(MainProductGroup.id.desc())
    if status is not None:
        stmt = stmt.where(MainProductGroup.status == status)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get("/pool-status", response_model=PoolStatusOut)
def get_pool_status(db: Session = Depends(get_db)) -> PoolStatusOut:
    """Dashboard'daki "havuz sağlığı" göstergesinin veri kaynağı — TASARIM.md
    §9 eki: ``--enable-order-stream`` olmadan uzun süre çalışan bir oturumun
    havuzu sessizce tüketebildiği bulgusu üzerine eklendi (2026-08-17)."""
    return PoolStatusOut(**crud.get_pool_status(db))


@router.get("/stream/status", response_model=OrderStreamStatusOut)
def get_order_stream_status(request: Request) -> OrderStreamStatusOut:
    stream = request.app.state.order_stream
    return OrderStreamStatusOut(running=stream.running, target_main_slabs=stream.target_main_slabs)


@router.post("/stream/start", response_model=OrderStreamStatusOut)
async def start_order_stream(body: OrderStreamStartRequest, request: Request, db: Session = Depends(get_db)) -> OrderStreamStatusOut:
    """Dashboard'daki "Otomatik Order Akışı" düğmesinin veri kaynağı —
    ``live_engine.py``'nin ``--enable-order-stream`` CLI bayrağıyla AYNI kod
    yolu (``order_stream.py``), ama API sürecinde runtime'da aç/kapatılabilir
    (TASARIM.md §9 eki, 2026-08-17).

    ``async def`` OLMASI GEREKİYOR (diğer uçların aksine) — içeride
    ``asyncio.create_task`` çağıran ``OrderStreamController.start``, çalışan
    bir event loop bulmalı; sync ``def`` FastAPI'de bir worker thread'e
    (loop'suz) düşürülür, orada ``RuntimeError: no running event loop``
    fırlatır (test sırasında bulundu, 2026-08-17)."""
    constraints: RollingConstraints = load_constraint_config(db)
    stream = request.app.state.order_stream
    stream.start(
        synthetic_config=_synthetic_config, constraints=constraints,
        target_main_slabs=body.target_main_slabs, seed=body.seed,
    )
    return OrderStreamStatusOut(running=stream.running, target_main_slabs=stream.target_main_slabs)


@router.post("/stream/stop", response_model=OrderStreamStatusOut)
async def stop_order_stream(request: Request) -> OrderStreamStatusOut:
    await request.app.state.order_stream.stop()
    return OrderStreamStatusOut(running=False, target_main_slabs=None)


@router.post("/reset-for-demo", response_model=ResetForDemoResponse)
async def reset_for_demo(body: ResetForDemoRequest, request: Request, db: Session = Depends(get_db)) -> ResetForDemoResponse:
    """Dashboard'daki tek-tuş "Sunuma Hazırla" düğmesi — TASARIM.md §9.4:
    kullanıcının her sunum/deneme öncesi elle tekrarladığı adımları
    (simülasyonu durdur, order-stream'i durdur, havuzu temizle, orantılı
    taze bir havuzla yeniden doldur) TEK bir çağrıda birleştirir.

    Varsayılan ``batches=25``, §9.3'te ölçülüp doğrulanan oranla AYNI
    (~3400 ana slab / ~300 geçiş order) — worker'ın hem çağrıldığı hem
    başarılı köprüler kurduğu gözlemlenen büyüklük.

    ``async def``: order-stream'i durdurmak için ``await`` gerekiyor
    (bkz. ``stop_order_stream``'in AYNI gerekçeli docstring'i) — bu aynı
    zamanda aşağıdaki yarış-durumu düzeltmesi için de GEREKLİ (``asyncio.sleep``)."""
    stream = request.app.state.order_stream
    stream_was_running = stream.running
    if stream_was_running:
        await stream.stop()

    simulation_stopped = False
    run = crud.get_latest_simulation_run(db)
    if run is not None and run.status != "stopped":
        try:
            control.stop(db, run.id)
            simulation_stopped = True
        except control.InvalidTransitionError:
            pass
        # YARIŞ DURUMU (test sırasında bulundu, 2026-08-17 — ilk düzeltme
        # YETERSİZDİ, bkz. not aşağıda): `live_engine.py` AYRI bir süreçtir,
        # `simulation_runs.status`'ü KENDİ (bu istekten TAMAMEN ayrı)
        # session'ında okur. `db.commit()` BURADA HEMEN çağrılmazsa, yukarıdaki
        # `control.stop()` bu fonksiyonun SONUNA kadar (havuz temizleme +
        # yeniden doldurma bittikten SONRA) commit edilmez — yani aşağıdaki
        # bekleme, motor durumu HİÇ göremediği için tamamen etkisizdi (ilk
        # sürümün gerçek hatası buydu). Şimdi ayrıca commit edilip motorun
        # bir sonraki döngü turunda GERÇEKTEN görmesi sağlanıyor.
        db.commit()
        if run.tick_interval_ms:
            await asyncio.sleep(max(1.0, 2 * run.tick_interval_ms / 1000))

    # İkinci bir güvenlik ağı: yukarıdaki bekleme sonrası bile motorun TAM o an
    # işlemekte olduğu (bekleme başlamadan hemen önce başlamış) bir adım hâlâ
    # bitmemiş olabilir. `clear_pending_pool` yine de bir FK ihlaliyle
    # çakışırsa, kısa bir bekleyip TEKRAR dene — art arda iki eş-zamanlı adım
    # aynı ana denk gelme ihtimali pratikte ihmal edilebilir.
    cleared_orders = cleared_groups = 0
    for attempt in range(3):
        try:
            cleared_orders, cleared_groups = crud.clear_pending_pool(db)
            db.commit()
            break
        except Exception:
            db.rollback()
            if attempt == 2:
                raise
            await asyncio.sleep(0.5)

    constraints: RollingConstraints = load_constraint_config(db)
    rng = random.Random(body.seed)
    inserted_orders = 0
    inserted_groups = 0
    for _ in range(body.batches):
        batch = generate_batch(_synthetic_config, constraints, rng)
        inserted_orders += crud.insert_generated_batch(db, batch)
        inserted_groups += len(batch.main_groups)

    crud.emit_event(
        db, event_type="order_generated",
        payload={"count": inserted_orders, "groups": inserted_groups, "reset_for_demo": True},
    )
    db.commit()

    return ResetForDemoResponse(
        simulation_stopped=simulation_stopped,
        stream_stopped=stream_was_running,
        cleared_orders=cleared_orders,
        cleared_groups=cleared_groups,
        inserted_orders=inserted_orders,
        inserted_groups=inserted_groups,
        pool_status=PoolStatusOut(**crud.get_pool_status(db)),
    )


@router.post("/generate", response_model=GenerateOrdersResponse)
def generate_orders(body: GenerateOrdersRequest, db: Session = Depends(get_db)) -> GenerateOrdersResponse:
    """TASARIM.md §5'in "canlı demo için opsiyonel özellik"iyle AYNI kod
    yolunu (``generate_batch`` + ``crud.insert_generated_batch``) kullanır
    — operatörün frontend'den elle "yeni sipariş partisi ekle" tetiklemesi
    içindir (``live_engine.background_order_generator`` bunun OTOMATİK/
    periyodik ikizidir, TASARIM.md §12.6)."""
    constraints: RollingConstraints = load_constraint_config(db)
    rng = random.Random(body.seed)

    cleared_orders = cleared_groups = 0
    if body.clear_pending:
        cleared_orders, cleared_groups = crud.clear_pending_pool(db)

    inserted_orders = 0
    inserted_groups = 0
    for _ in range(body.batches):
        batch = generate_batch(_synthetic_config, constraints, rng)
        inserted_orders += crud.insert_generated_batch(db, batch)
        inserted_groups += len(batch.main_groups)

    crud.emit_event(db, event_type="order_generated", payload={"count": inserted_orders, "groups": inserted_groups})
    db.commit()
    return GenerateOrdersResponse(
        inserted_orders=inserted_orders,
        inserted_groups=inserted_groups,
        cleared_orders=cleared_orders,
        cleared_groups=cleared_groups,
    )
