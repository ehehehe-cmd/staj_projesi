from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SlabOrder(Base):
    """TASARIM.md §3.1 — ham order havuzu."""

    __tablename__ = "slab_orders"
    __table_args__ = (
        CheckConstraint("order_class IN ('main', 'transition')", name="ck_slab_orders_order_class"),
        CheckConstraint(
            "status IN ('pending', 'reserved', 'scheduled', 'in_progress', 'completed', 'skipped')",
            name="ck_slab_orders_status",
        ),
        CheckConstraint("source IN ('synthetic', 'manual')", name="ck_slab_orders_source"),
        Index("ix_slab_orders_status", "status"),
        Index("ix_slab_orders_main_group_id", "main_group_id"),
        Index("ix_slab_orders_order_class_status", "order_class", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(50))
    steel_grade: Mapped[str | None] = mapped_column(String(50))
    width_mm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(8, 3))
    hardness: Mapped[float | None] = mapped_column(Numeric(6, 2))
    heating_temp_c: Mapped[float | None] = mapped_column(Numeric(6, 2))
    slab_width_mm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    slab_thickness_mm: Mapped[float | None] = mapped_column(Numeric(8, 3))
    slab_length_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    theoretical_rolling_length: Mapped[float | None] = mapped_column(Numeric(12, 3))
    order_class: Mapped[str] = mapped_column(String(20))
    # Çember bağımlılığı: main_product_groups da slab_orders'a FK veriyor (first/last_order_id).
    # use_alter=True, SQLAlchemy/Alembic'in bu FK'yi ayrı bir ALTER TABLE adımında kurmasını sağlar.
    main_group_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("main_product_groups.id", use_alter=True, name="fk_slab_orders_main_group_id"),
    )
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MainProductGroup(Base):
    """TASARIM.md §3.2 — Nₖ = (s_first, s_last, L_Nₖ) soyutlaması."""

    __tablename__ = "main_product_groups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('available', 'scheduled', 'partially_used')",
            name="ck_main_product_groups_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    steel_grade: Mapped[str | None] = mapped_column(String(50))
    first_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("slab_orders.id"))
    last_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("slab_orders.id"))
    group_size: Mapped[int | None] = mapped_column(Integer)
    initial_group_size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), server_default="available")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RollingCourse(Base):
    """TASARIM.md §3.3 — haddeleme kursları (j)."""

    __tablename__ = "rolling_courses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'completed', 'failed')",
            name="ck_rolling_courses_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_number: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    min_orders: Mapped[int | None] = mapped_column(Integer)
    max_orders: Mapped[int | None] = mapped_column(Integer)
    first_main_group_placed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    current_length_mm: Mapped[float | None] = mapped_column(Numeric(14, 3))
    reverse_width_events_count: Mapped[int] = mapped_column(Integer, server_default="0")
    order_count: Mapped[int] = mapped_column(Integer, server_default="0")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CourseSlot(Base):
    """TASARIM.md §3.4 — bir kurstaki sıralı pozisyonlar (k)."""

    __tablename__ = "course_slots"
    __table_args__ = (
        UniqueConstraint("course_id", "position_index", name="uq_course_slots_course_position"),
        CheckConstraint("role IN ('main', 'transition')", name="ck_course_slots_role"),
        Index("ix_course_slots_course_position", "course_id", "position_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rolling_courses.id"))
    position_index: Mapped[int] = mapped_column(Integer)
    slab_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("slab_orders.id"))
    role: Mapped[str] = mapped_column(String(20))
    width_mm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(8, 3))
    hardness: Mapped[float | None] = mapped_column(Numeric(6, 2))
    heating_temp_c: Mapped[float | None] = mapped_column(Numeric(6, 2))
    cumulative_length_mm: Mapped[float | None] = mapped_column(Numeric(14, 3))
    is_reverse_width: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManagerDecision(Base):
    """TASARIM.md §3.5 — Manager ajanının her adımdaki kararı."""

    __tablename__ = "manager_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rolling_courses.id"))
    step_index: Mapped[int] = mapped_column(Integer)
    state_snapshot: Mapped[dict] = mapped_column(JSONB)
    action_mask: Mapped[dict] = mapped_column(JSONB)
    selected_group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("main_product_groups.id"))
    reward: Mapped[float | None] = mapped_column(Numeric(10, 5))
    model_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("model_versions.id"))
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkerDecision(Base):
    """TASARIM.md §3.6 — Worker ajanının geçiş slabı seçimleri."""

    __tablename__ = "worker_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    manager_decision_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("manager_decisions.id"))
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rolling_courses.id"))
    step_index: Mapped[int] = mapped_column(Integer)
    state_snapshot: Mapped[dict] = mapped_column(JSONB)
    action_mask: Mapped[dict] = mapped_column(JSONB)
    selected_transition_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("slab_orders.id"))
    success: Mapped[bool | None] = mapped_column(Boolean)
    reward: Mapped[float | None] = mapped_column(Numeric(10, 5))
    model_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("model_versions.id"))
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveEvent(Base):
    """TASARIM.md §3.7 — append-only olay akışı (NOTIFY payload kaynağı)."""

    __tablename__ = "live_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'order_generated', 'course_started', 'main_group_selected', 'transition_selected', "
            "'slab_placed', 'course_completed', 'course_failed', 'constraint_violation', "
            "'simulation_started', 'simulation_paused', 'simulation_resumed', 'simulation_stopped', "
            "'manual_step')",
            name="ck_live_events_event_type",
        ),
        Index("ix_live_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40))
    course_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("rolling_courses.id"))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulationRun(Base):
    """TASARIM.md §3.8 — canlı motorun oturumları."""

    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('autonomous', 'manual', 'hybrid')", name="ck_simulation_runs_mode"),
        CheckConstraint("status IN ('running', 'paused', 'stopped')", name="ck_simulation_runs_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    tick_interval_ms: Mapped[int | None] = mapped_column(Integer)
    manager_model_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("model_versions.id"))
    worker_model_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("model_versions.id"))
    config: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ModelVersion(Base):
    """TASARIM.md §3.9 — eğitilmiş checkpoint kayıtları."""

    __tablename__ = "model_versions"
    __table_args__ = (CheckConstraint("level IN ('manager', 'worker')", name="ck_model_versions_level"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    level: Mapped[str] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(String(100))
    checkpoint_path: Mapped[str | None] = mapped_column(Text)
    trained_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    training_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("training_runs.id"))
    hyperparams: Mapped[dict | None] = mapped_column(JSONB)
    metrics: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingRun(Base):
    """TASARIM.md §3.10 — offline eğitim oturumu metadata'sı (hot-path değildir)."""

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    seed: Mapped[int | None] = mapped_column(Integer)
    episodes: Mapped[int | None] = mapped_column(Integer)
    hyperparams: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConstraintConfig(Base):
    """TASARIM.md §3.11 — ayarlanabilir fiziksel kısıt eşikleri."""

    __tablename__ = "constraint_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    value: Mapped[float] = mapped_column(Numeric)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ActiveCourseStateRow(Base):
    """TASARIM.md §3.12 — ``v_active_course_state`` view'inin salt-okunur ORM
    karşılığı. View, Faz 1 migration'ında (``41dbbfae3279``) zaten
    oluşturulmuştu; ORM eşlemesi ilk gerçek çağıranı olan Faz 6'nın
    ``GET /api/courses/active`` route'u için burada eklendi (bkz. §12.7).

    View'in kendi PK'ı yok (bir ``rolling_courses``⋈``course_slots`` join'i);
    ``(course_id, position_index)`` ORM'un satır kimliği için yeterince
    benzersizdir — asla INSERT/UPDATE edilmez, salt SELECT amaçlıdır.
    """

    __tablename__ = "v_active_course_state"
    __table_args__ = {"info": {"is_view": True}}

    course_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    order_count: Mapped[int] = mapped_column(Integer)
    current_length_mm: Mapped[float | None] = mapped_column(Numeric(14, 3))
    reverse_width_events_count: Mapped[int] = mapped_column(Integer)
    position_index: Mapped[int | None] = mapped_column(Integer, primary_key=True)
    role: Mapped[str | None] = mapped_column(String(20))
    width_mm: Mapped[float | None] = mapped_column(Numeric(8, 2))
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(8, 3))
    hardness: Mapped[float | None] = mapped_column(Numeric(6, 2))
    heating_temp_c: Mapped[float | None] = mapped_column(Numeric(6, 2))
    is_reverse_width: Mapped[bool | None] = mapped_column(Boolean)
    slab_order_id: Mapped[int | None] = mapped_column(BigInteger)
