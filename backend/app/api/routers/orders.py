"""``GET /api/orders``, ``GET /api/orders/groups``, ``POST /api/orders/generate``
— TASARIM.md §4. "order-pool" özelliğinin (§9: "bekleyen ana gruplar + geçiş
order havuzu, filtrelenebilir liste") veri kaynağı.
"""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import GenerateOrdersRequest, GenerateOrdersResponse, MainGroupOut, SlabOrderOut
from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud
from app.db.crud import load_constraint_config
from app.db.models import MainProductGroup, SlabOrder

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
    stmt = select(SlabOrder).order_by(SlabOrder.id)
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
    stmt = select(MainProductGroup).order_by(MainProductGroup.id)
    if status is not None:
        stmt = stmt.where(MainProductGroup.status == status)
    stmt = stmt.offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


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
