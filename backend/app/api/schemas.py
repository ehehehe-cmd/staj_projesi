"""Pydantic response/request modelleri — TASARIM.md §4, §12.7.

Bu modül TEK sorumluluk taşır: ORM satırları (``db/models.py``) ile HTTP
JSON gövdeleri arasındaki dönüşüm sözleşmesi. İş mantığı (DB sorguları,
state machine kuralları) burada YAZILMAZ — router'lar ``db/crud.py`` ve
``simulation/control.py``'yi çağırır, bu modül yalnızca şekli tanımlar.

``state_snapshot``/``action_mask`` (ham ``to_vector()`` çıktısı, K_max/P_max
boyutlu) BİLİNÇLİ OLARAK dışa aktarılmaz — bunlar iç/hata-ayıklama verisidir;
frontend'in belgelenmiş özellikleri (decision-log, dashboard) yalnızca "kim
ne seçti, ne zaman, ödül neydi"ye ihtiyaç duyar (TASARIM.md §9).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── orders ──────────────────────────────────────────────────────────


class SlabOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_ref: str | None
    steel_grade: str | None
    width_mm: float | None
    thickness_mm: float | None
    hardness: float | None
    heating_temp_c: float | None
    slab_width_mm: float | None
    slab_thickness_mm: float | None
    slab_length_mm: float | None
    theoretical_rolling_length: float | None
    order_class: str
    main_group_id: int | None
    status: str
    source: str
    created_at: dt.datetime


class MainGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    steel_grade: str | None
    first_order_id: int | None
    last_order_id: int | None
    group_size: int | None
    initial_group_size: int | None
    status: str
    created_at: dt.datetime


class GenerateOrdersRequest(BaseModel):
    seed: int | None = None
    batches: int = Field(default=1, ge=1, le=20)
    clear_pending: bool = False


class GenerateOrdersResponse(BaseModel):
    inserted_orders: int
    inserted_groups: int
    cleared_orders: int = 0
    cleared_groups: int = 0


# ── courses ─────────────────────────────────────────────────────────


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_number: int
    status: str
    min_orders: int | None
    max_orders: int | None
    first_main_group_placed: bool
    current_length_mm: float | None
    reverse_width_events_count: int
    order_count: int
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    created_at: dt.datetime


class CourseSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    position_index: int
    slab_order_id: int | None
    role: str
    width_mm: float | None
    thickness_mm: float | None
    hardness: float | None
    heating_temp_c: float | None
    cumulative_length_mm: float | None
    is_reverse_width: bool
    created_at: dt.datetime


class CourseDetailOut(CourseOut):
    slots: list[CourseSlotOut]


class ActiveCourseSlotOut(BaseModel):
    """``v_active_course_state`` (TASARIM.md §3.12) satırının HTTP karşılığı."""

    model_config = ConfigDict(from_attributes=True)

    position_index: int | None
    role: str | None
    width_mm: float | None
    thickness_mm: float | None
    hardness: float | None
    heating_temp_c: float | None
    is_reverse_width: bool | None
    slab_order_id: int | None


class ActiveCourseOut(BaseModel):
    course_id: int
    course_number: int
    status: str
    order_count: int
    current_length_mm: float | None
    reverse_width_events_count: int
    slots: list[ActiveCourseSlotOut]


# ── decisions ───────────────────────────────────────────────────────


class ManagerDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["manager"] = "manager"
    id: int
    course_id: int
    step_index: int
    selected_group_id: int | None
    reward: float | None
    model_version_id: int | None
    decided_at: dt.datetime


class WorkerDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["worker"] = "worker"
    id: int
    manager_decision_id: int
    course_id: int
    step_index: int
    selected_transition_order_id: int | None
    success: bool | None
    reward: float | None
    model_version_id: int | None
    decided_at: dt.datetime


DecisionItem = Annotated[ManagerDecisionOut | WorkerDecisionOut, Field(discriminator="kind")]


class DecisionsPage(BaseModel):
    items: list[DecisionItem]
    next_since: dt.datetime | None


# ── models ──────────────────────────────────────────────────────────


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    name: str | None
    checkpoint_path: str | None
    trained_at: dt.datetime | None
    hyperparams: dict | None
    metrics: dict | None
    is_active: bool
    created_at: dt.datetime


class ActiveModelsOut(BaseModel):
    manager: ModelVersionOut | None
    worker: ModelVersionOut | None


# ── simulation ──────────────────────────────────────────────────────


class SimulationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    status: str
    tick_interval_ms: int | None
    manager_model_version_id: int | None
    worker_model_version_id: int | None
    config: dict | None
    started_at: dt.datetime | None
    stopped_at: dt.datetime | None


class SimulationStartRequest(BaseModel):
    mode: Literal["autonomous", "manual", "hybrid"] = "hybrid"
    tick_interval_ms: int | None = None
    config: dict | None = None


# ── genel ───────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    detail: str
