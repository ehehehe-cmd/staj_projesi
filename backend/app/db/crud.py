"""DB yazma/okuma yardımcıları — bu fazın (Faz 3) ilk gerçek çağıranı
``scripts/seed_db.py``'dir (bkz. TASARIM.md §12.2.1: bu dosya Faz 1'de
kasıtlı olarak boş bırakılmıştı, "gerçek bir çağıran ortaya çıktığında
yazılacaktı").

İsimlendirme notu: ``app.db.models.ConstraintConfig`` (ORM satır modeli) ile
``app.core.constraints.RollingConstraints`` (domain değer nesnesi) arasında
isim çakışması olmasın diye bu modül ikisini de açıkça farklı adlarla
kullanır (bkz. TASARIM.md §12.3.3.1).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Set as AbstractSet

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.core.constraints import RollingConstraints
from app.data_generation.generator import GeneratedBatch
from app.domain import transition_rules
from app.domain.action_mask import CourseProgress
from app.domain.dto import MainGroupDTO, OrderAttributes, TransitionOrderDTO
from app.db.models import (
    ConstraintConfig,
    CourseSlot,
    LiveEvent,
    MainProductGroup,
    ManagerDecision,
    ModelVersion,
    RollingCourse,
    SimulationRun,
    SlabOrder,
    TrainingRun,
    WorkerDecision,
)


def load_constraint_config(session: Session) -> RollingConstraints:
    """``constraint_config`` tablosunun 9 satırını ``RollingConstraints``'e
    dönüştürür (TASARIM.md §3.11, §1 ilke 6: "config-driven kısıtlar")."""
    rows = session.execute(select(ConstraintConfig.key, ConstraintConfig.value)).all()
    values = {key: value for key, value in rows}
    return RollingConstraints.from_mapping(values)


def clear_pending_pool(session: Session) -> tuple[int, int]:
    """Mevcut ``pending`` order havuzunu ve bunlara bağlı ``available``
    grupları temizler; ``(silinen_order_sayısı, silinen_grup_sayısı)``
    döndürür.

    Dairesel FK (``slab_orders.main_group_id`` ↔
    ``main_product_groups.first_order_id``/``last_order_id``, bkz.
    TASARIM.md §12.2.3.3) nedeniyle sıra kritiktir:
      1) önce ``slab_orders → main_product_groups`` kenarı kırılır
         (``main_group_id = NULL``),
      2) ``manager_decisions.selected_group_id`` kenarı da kırılır — bir
         grup SEÇİLİP (karar kaydedilip) hiç YERLEŞTİRİLMEMİŞ olabilir
         (ör. worker'a devredilip köprü adayı bulunamadığı için elenmiş);
         bu durumda grubun ``status``'ü hâlâ ``available``'dır ama
         ``manager_decisions`` ona referans verir — bu kırılmazsa silme
         FK ihlaliyle patlar (canlı bir simülasyonun ARDINDAN çağrılırken
         test sırasında bulundu, 2026-08-17, bkz. TASARIM.md §9.4). Karar
         GEÇMİŞİ silinmez, yalnızca artık var olmayacak gruba işaret eden
         referans NULL'lanır (``selected_group_id`` zaten nullable — "kursu
         kapat" kararları da bunu None tutar).
      3) artık kimse tarafından referans edilmeyen gruplar silinir,
      4) en son pending order'ların kendisi silinir (artık hiçbir grup
         onlara ``first_order_id``/``last_order_id`` ile referans etmiyor).
    """
    session.execute(update(SlabOrder).where(SlabOrder.status == "pending").values(main_group_id=None))
    session.execute(
        update(ManagerDecision)
        .where(ManagerDecision.selected_group_id.in_(select(MainProductGroup.id).where(MainProductGroup.status == "available")))
        .values(selected_group_id=None)
    )
    deleted_groups = session.execute(
        delete(MainProductGroup).where(MainProductGroup.status == "available")
    ).rowcount
    deleted_orders = session.execute(delete(SlabOrder).where(SlabOrder.status == "pending")).rowcount
    return deleted_orders, deleted_groups


def insert_generated_batch(session: Session, batch: GeneratedBatch) -> int:
    """``generator.generate_batch()`` çıktısını ``slab_orders`` +
    ``main_product_groups`` tablolarına yazar; eklenen order sayısını
    döndürür.

    Ekleme sırası, dairesel FK'yi ``clear_pending_pool`` ile simetrik
    şekilde ele alır: önce TÜM order'lar (main_group_id boş) eklenir,
    sonra gruplar (first/last_order_id artık gerçek DB id'lerine işaret
    edebilir) eklenir, en son her grubun üyesi olan order'ların
    ``main_group_id``'si toplu ``UPDATE`` ile set edilir.
    """
    local_to_db_id: dict[int, int] = {}
    for order in batch.orders:
        row = SlabOrder(
            steel_grade=order.steel_grade,
            width_mm=order.width_mm,
            thickness_mm=order.thickness_mm,
            hardness=order.hardness,
            heating_temp_c=order.heating_temp_c,
            slab_width_mm=order.slab_width_mm,
            slab_thickness_mm=order.slab_thickness_mm,
            slab_length_mm=order.slab_length_mm,
            theoretical_rolling_length=order.rolling_length(),
            order_class=order.order_class,
            status="pending",
            source="synthetic",
        )
        session.add(row)
        session.flush()
        local_to_db_id[order.id] = row.id

    for group in batch.main_groups:
        db_member_ids = [local_to_db_id[local_id] for local_id in group.member_order_ids]
        group_row = MainProductGroup(
            steel_grade=group.steel_grade,
            first_order_id=db_member_ids[0],
            last_order_id=db_member_ids[-1],
            group_size=group.group_size,
            initial_group_size=group.initial_group_size,
            status="available",
        )
        session.add(group_row)
        session.flush()
        session.execute(
            update(SlabOrder).where(SlabOrder.id.in_(db_member_ids)).values(main_group_id=group_row.id)
        )

    return len(batch.orders)


def record_training_run(
    session: Session,
    *,
    started_at: dt.datetime,
    ended_at: dt.datetime,
    seed: int,
    episodes: int,
    hyperparams: dict,
    notes: str = "",
) -> int:
    """``training_runs``'a TEK SEFERLİK bir satır yazar (TASARIM.md §3.10,
    §6: "hot-path DEĞİLDİR; sadece eğitim bitince bir kez yazılır"). İlk
    gerçek çağıranı ``training/train.py``'dir (Faz 4)."""
    row = TrainingRun(
        started_at=started_at,
        ended_at=ended_at,
        seed=seed,
        episodes=episodes,
        hyperparams=hyperparams,
        notes=notes,
    )
    session.add(row)
    session.flush()
    return row.id


def record_model_version(
    session: Session,
    *,
    level: str,
    name: str,
    checkpoint_path: str,
    trained_at: dt.datetime,
    training_run_id: int,
    hyperparams: dict,
    metrics: dict,
) -> int:
    """``model_versions``'a bir checkpoint kaydı ekler — TASARIM.md §3.9:
    ``is_active`` bilinçli olarak burada set EDİLMEZ (varsayılan false
    kalır); aktifleştirme ayrı bir adımdır (bkz. ``scripts/activate_model.py``,
    §6: "küçük bir admin script/SQL ile")."""
    row = ModelVersion(
        level=level,
        name=name,
        checkpoint_path=checkpoint_path,
        trained_at=trained_at,
        training_run_id=training_run_id,
        hyperparams=hyperparams,
        metrics=metrics,
        is_active=False,
    )
    session.add(row)
    session.flush()
    return row.id


def activate_model_version(session: Session, *, model_version_id: int) -> int:
    """Belirtilen ``model_versions`` satırını ``is_active=true`` yapar ve
    AYNI ``level``'daki (manager/worker) diğer tüm satırları ``false``'a
    çeker — TASARIM.md §1 ilke 5 (model registry ile hot-swap): "yeni bir
    model eğitildiğinde sadece bu bayrak güncellenir, kod değişmez."
    Döner: false'a çekilen satır sayısı (bilgi amaçlı)."""
    target = session.get(ModelVersion, model_version_id)
    if target is None:
        raise ValueError(f"model_versions.id={model_version_id} bulunamadı")
    deactivated = session.execute(
        update(ModelVersion)
        .where(ModelVersion.level == target.level, ModelVersion.id != model_version_id)
        .values(is_active=False)
    ).rowcount
    session.execute(update(ModelVersion).where(ModelVersion.id == model_version_id).values(is_active=True))
    return deactivated


# ═══════════════════════════════════════════════════════════════════════
# Faz 5 — canlı simülasyon motoru (TASARIM.md §7, §12.6). Bu bölümdeki
# fonksiyonlar ``app/simulation/*.py``'nin TEK DB erişim katmanıdır — Faz
# 2/3/4'ün "domain mantığı asla DB'ye dokunmaz" ayrımıyla simetrik olarak,
# ``live_engine.py`` de kendi ORM sorgularını YAZMAZ, hepsini buradan çağırır.
# ═══════════════════════════════════════════════════════════════════════


def get_active_model_version(session: Session, *, level: str) -> ModelVersion | None:
    """``model_versions``'ta ``level`` (manager/worker) için ``is_active=true``
    olan satırı döndürür (yoksa ``None`` — çağıran karar verir)."""
    return session.execute(
        select(ModelVersion).where(ModelVersion.level == level, ModelVersion.is_active.is_(True))
    ).scalar_one_or_none()


def get_active_course(session: Session) -> RollingCourse | None:
    """``rolling_courses`` içinde ``status='active'`` olan satırı döndürür —
    crash-recovery'nin giriş noktası (TASARIM.md §1 ilke 7)."""
    return session.execute(select(RollingCourse).where(RollingCourse.status == "active")).scalar_one_or_none()


def start_new_course(session: Session, *, constraints: RollingConstraints) -> RollingCourse:
    """Sıradaki ``course_number``'la yeni bir ``rolling_courses`` satırı açar
    (``status='active'``, ``min_orders``/``max_orders`` o anki
    ``constraint_config``'ten SNAPSHOT alınır — TASARIM.md §3.3). Bir
    ``course_started`` olayı YAZMAZ; bunun course_id'ye ihtiyacı olduğu için
    (satır önce flush edilmeli) çağıranın (``live_engine``) sorumluluğundadır.
    """
    last_number = session.execute(select(func.max(RollingCourse.course_number))).scalar()
    course = RollingCourse(
        course_number=(last_number or 0) + 1,
        status="active",
        min_orders=constraints.m_min,
        max_orders=constraints.m_max,
        first_main_group_placed=False,
        current_length_mm=0,
        reverse_width_events_count=0,
        order_count=0,
        started_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(course)
    session.flush()
    return course


def load_course_progress(session: Session, course: RollingCourse) -> CourseProgress:
    """``CourseProgress``'i (Im, max_orders, C_j,k, reverse sayacı, s_t)
    TASARIM.md §1 ilke 7'nin öngördüğü gibi SADECE ``rolling_courses`` +
    ``course_slots``'tan yeniden inşa eder — crash-recovery'nin kalbi."""
    last_slot = session.execute(
        select(CourseSlot)
        .where(CourseSlot.course_id == course.id)
        .order_by(CourseSlot.position_index.desc())
        .limit(1)
    ).scalar_one_or_none()
    last_attributes = None
    if last_slot is not None:
        last_attributes = OrderAttributes(
            width_mm=float(last_slot.width_mm),
            thickness_mm=float(last_slot.thickness_mm),
            hardness=float(last_slot.hardness),
            heating_temp_c=float(last_slot.heating_temp_c),
        )
    return CourseProgress(
        order_count=course.order_count,
        max_orders=course.max_orders,
        cumulative_length_mm=float(course.current_length_mm or 0.0),
        reverse_width_events_count=course.reverse_width_events_count,
        last_attributes=last_attributes,
    )


def count_manager_decisions(session: Session, course_id: int) -> int:
    """Bir kurs için şimdiye kadar yazılmış ``manager_decisions`` satırı
    sayısı — crash-recovery sonrası ``step_index``'in (İN-MEMORY sayaç
    yeniden başladığında) ÖNCEKİ kayıtlarla ÇAKIŞMAMASI için ``live_engine``
    tarafından bir kursa "yeniden katılırken" okunur (bkz. TASARIM.md §12.6:
    step_index kesinlikle artan/benzersiz kalmalı)."""
    return session.execute(
        select(func.count()).select_from(ManagerDecision).where(ManagerDecision.course_id == course_id)
    ).scalar_one()


def count_main_slots(session: Session, course_id: int) -> int:
    """Bir kursa şimdiye kadar yerleştirilmiş ``role='main'`` slot sayısı —
    crash-recovery sonrası R^m'nin (eş. 34) kurs-bazlı ``cov`` payı
    hesaplamasında kullanılan ``_course_main_orders_used`` sayacını DB'den
    yeniden inşa etmek için (bkz. ``live_engine._close_course``)."""
    return session.execute(
        select(func.count()).select_from(CourseSlot).where(CourseSlot.course_id == course_id, CourseSlot.role == "main")
    ).scalar_one()


def sum_available_group_sizes(session: Session) -> int:
    """Halen tüketilmemiş (``group_size > 0``) tüm ana gruplardaki toplam
    order sayısı — canlı ortamda sınırsız/sürekli akan havuzun R^m (eş. 32-34)
    hesaplamasında kullanılan bir "orders_total" yerine geçen pragmatik
    yaklaşım için (bkz. ``live_engine._close_course``, TASARIM.md §12.6)."""
    return session.execute(
        select(func.coalesce(func.sum(MainProductGroup.group_size), 0)).where(MainProductGroup.group_size > 0)
    ).scalar_one()


def get_pool_status(session: Session) -> dict[str, int]:
    """Canlı havuzun ne kadarının kaldığı — dashboard'daki "havuz sağlığı"
    göstergesi için (TASARIM.md §9 eki, 2026-08-17: ``--enable-order-stream``
    olmadan uzun süre çalışan bir oturumun havuzu sessizce tüketebildiği
    bulgusu üzerine eklendi, bkz. docs/SONUCLAR.md)."""
    remaining_groups = session.execute(
        select(func.count()).select_from(MainProductGroup).where(MainProductGroup.group_size > 0)
    ).scalar_one()
    remaining_slabs = sum_available_group_sizes(session)
    remaining_transitions = session.execute(
        select(func.count())
        .select_from(SlabOrder)
        .where(SlabOrder.order_class == "transition", SlabOrder.status == "pending")
    ).scalar_one()
    return {
        "remaining_main_groups": remaining_groups,
        "remaining_main_slabs": remaining_slabs,
        "remaining_transition_orders": remaining_transitions,
    }


def load_available_groups(
    session: Session,
    *,
    limit: int,
    exclude_ids: AbstractSet[int] = frozenset(),
    last_attributes: OrderAttributes | None = None,
    constraints: RollingConstraints | None = None,
) -> list[MainGroupDTO]:
    """Görünür ana grup havuzu — ``training/env.py``'nin ``_visible_groups``'ıyla
    aynı semantik.

    TASARIM.md §14.3.E: ``last_attributes`` VE ``constraints`` birlikte
    verilirse, en fazla ``limit`` adetlik pencere FIFO (``id`` sırası)
    yerine ``transition_rules.sort_groups_by_proximity`` ile (şu anki
    ``last_attributes``'a en yakın gruplar önce) belirlenir — ``env.py``
    ile TEK kaynak (İlke 1). İkisinden biri eksikse (varsayılan) eski
    FIFO davranışı birebir korunur — id sırasıyla kararlı, tükenmemiş,
    en fazla ``limit`` adet.
    """
    rows = session.execute(
        select(MainProductGroup).where(MainProductGroup.group_size > 0).order_by(MainProductGroup.id)
    ).scalars().all()
    candidates = [r for r in rows if r.id not in exclude_ids]

    use_proximity = last_attributes is not None and constraints is not None
    if not use_proximity:
        candidates = candidates[:limit]

    dtos: list[MainGroupDTO] = []
    for row in candidates:
        first = session.get(SlabOrder, row.first_order_id)
        last = session.get(SlabOrder, row.last_order_id)
        dtos.append(
            MainGroupDTO(
                id=row.id,
                steel_grade=row.steel_grade,
                first=OrderAttributes(
                    width_mm=float(first.width_mm),
                    thickness_mm=float(first.thickness_mm),
                    hardness=float(first.hardness),
                    heating_temp_c=float(first.heating_temp_c),
                ),
                last=OrderAttributes(
                    width_mm=float(last.width_mm),
                    thickness_mm=float(last.thickness_mm),
                    hardness=float(last.hardness),
                    heating_temp_c=float(last.heating_temp_c),
                ),
                group_size=row.group_size,
                initial_group_size=row.initial_group_size,
            )
        )
    if use_proximity:
        dtos = transition_rules.sort_groups_by_proximity(dtos, last_attributes, constraints)[:limit]
    return dtos


def load_available_transitions(session: Session, *, limit: int) -> list[TransitionOrderDTO]:
    """Görünür geçiş order havuzu — ``status='pending'`` olan
    ``order_class='transition'`` satırları. TASARIM.md §12.5 karar #5'in
    canlı karşılığı: bir order ``status``'ü ``pending``'ten çıktığı an bu
    sorgudan bir daha hiç dönmez, yani "global ve kalıcı tüketim" burada
    ekstra bir muhasebe yapısı GEREKTİRMEDEN DB durumunun kendisiyle sağlanır.
    """
    rows = session.execute(
        select(SlabOrder)
        .where(SlabOrder.order_class == "transition", SlabOrder.status == "pending")
        .order_by(SlabOrder.id)
        .limit(limit)
    ).scalars().all()
    return [
        TransitionOrderDTO(
            id=r.id,
            steel_grade=r.steel_grade,
            width_mm=float(r.width_mm),
            thickness_mm=float(r.thickness_mm),
            hardness=float(r.hardness),
            heating_temp_c=float(r.heating_temp_c),
        )
        for r in rows
    ]


def consume_group_members(session: Session, *, group_id: int, take: int) -> list[SlabOrder]:
    """Bir ana gruptan en fazla ``take`` adet ``pending`` order'ı (id
    sırasıyla — ``training/env.py``'nin ``_GroupState.remaining_ids.pop(0)``
    FIFO'suyla birebir aynı semantik) çeker, ``scheduled`` işaretler, grubun
    ``group_size``/``status``'ünü günceller (tükendiyse ``'scheduled'``,
    kalan varsa ``'partially_used'`` — TASARIM.md §12.6'daki yorum kararı).
    Döner: yerleştirilen (henüz ``course_slots``'a YAZILMAMIŞ) order satırları
    — cumulative_length/reverse-width muhasebesi tek tek uygulanabilsin diye
    bu, ÇAĞIRANIN (``live_engine``) sorumluluğundadır.
    """
    group = session.get(MainProductGroup, group_id)
    if group is None:
        raise ValueError(f"main_product_groups.id={group_id} bulunamadı")
    rows = session.execute(
        select(SlabOrder)
        .where(SlabOrder.main_group_id == group_id, SlabOrder.status == "pending")
        .order_by(SlabOrder.id)
        .limit(take)
    ).scalars().all()
    if rows:
        ids = [r.id for r in rows]
        session.execute(update(SlabOrder).where(SlabOrder.id.in_(ids)).values(status="scheduled"))
    group.group_size = group.group_size - len(rows)
    group.status = "scheduled" if group.group_size <= 0 else "partially_used"
    session.flush()
    return list(rows)


def consume_transition_order(session: Session, *, order_id: int) -> SlabOrder:
    """Tek bir geçiş order'ını ``scheduled`` işaretler (worker'ın seçimi)."""
    order = session.get(SlabOrder, order_id)
    if order is None:
        raise ValueError(f"slab_orders.id={order_id} bulunamadı")
    order.status = "scheduled"
    session.flush()
    return order


def append_course_slot(
    session: Session,
    *,
    course: RollingCourse,
    slab_order: SlabOrder,
    role: str,
    cumulative_length_mm: float,
    reverse_width_events_count: int,
    is_reverse_width: bool,
) -> CourseSlot:
    """Bir ``course_slots`` satırı ekler ve ``rolling_courses``'un ilerleme
    alanlarını (``order_count``, ``current_length_mm``,
    ``reverse_width_events_count``, ``first_main_group_placed``) AYNI anda
    günceller — ``course`` nesnesi çağıranda da aynı ORM referansı olduğu
    için bu mutasyon çağıranda da hemen görünür olur."""
    slot = CourseSlot(
        course_id=course.id,
        position_index=course.order_count,
        slab_order_id=slab_order.id,
        role=role,
        width_mm=slab_order.width_mm,
        thickness_mm=slab_order.thickness_mm,
        hardness=slab_order.hardness,
        heating_temp_c=slab_order.heating_temp_c,
        cumulative_length_mm=cumulative_length_mm,
        is_reverse_width=is_reverse_width,
    )
    session.add(slot)
    course.order_count += 1
    course.current_length_mm = cumulative_length_mm
    course.reverse_width_events_count = reverse_width_events_count
    if role == "main":
        course.first_main_group_placed = True
    session.flush()
    return slot


def complete_course(session: Session, course: RollingCourse, *, m_min: int) -> str:
    """Kursu kapatır: ``order_count >= m_min`` ise ``'completed'``, aksi
    halde ``'failed'`` (TASARIM.md §12.6 — şemadaki ``rolling_courses.status``
    'failed' değerine somut bir anlam kazandıran yorum kararı: m_min'in
    altında kalan bir kurs, eş. 33'ün cap cezasının da zaten "başarısız"
    saydığı bir kurstur). Kursa ait tüm ``scheduled`` order'ları
    ``'completed'`` yapar. Döner: verilen nihai status."""
    status = "completed" if course.order_count >= m_min else "failed"
    course.status = status
    course.completed_at = dt.datetime.now(dt.timezone.utc)
    session.execute(
        update(SlabOrder)
        .where(
            SlabOrder.id.in_(select(CourseSlot.slab_order_id).where(CourseSlot.course_id == course.id)),
            SlabOrder.status == "scheduled",
        )
        .values(status="completed")
    )
    session.flush()
    return status


def record_manager_decision(
    session: Session,
    *,
    course_id: int,
    step_index: int,
    vector: list[float],
    eligible_group_ids: list[int],
    selected_group_id: int | None,
    reward: float,
    model_version_id: int,
) -> ManagerDecision:
    row = ManagerDecision(
        course_id=course_id,
        step_index=step_index,
        state_snapshot={"vector": vector},
        action_mask=eligible_group_ids,
        selected_group_id=selected_group_id,
        reward=reward,
        model_version_id=model_version_id,
    )
    session.add(row)
    session.flush()
    return row


def record_worker_decision(
    session: Session,
    *,
    manager_decision_id: int,
    course_id: int,
    step_index: int,
    vector: list[float],
    eligible_transition_ids: list[int],
    selected_transition_order_id: int | None,
    success: bool | None,
    reward: float,
    model_version_id: int,
) -> WorkerDecision:
    row = WorkerDecision(
        manager_decision_id=manager_decision_id,
        course_id=course_id,
        step_index=step_index,
        state_snapshot={"vector": vector},
        action_mask=eligible_transition_ids,
        selected_transition_order_id=selected_transition_order_id,
        success=success,
        reward=reward,
        model_version_id=model_version_id,
    )
    session.add(row)
    session.flush()
    return row


def record_live_event(
    session: Session, *, event_type: str, course_id: int | None = None, payload: dict | None = None
) -> LiveEvent:
    row = LiveEvent(event_type=event_type, course_id=course_id, payload=payload or {})
    session.add(row)
    session.flush()
    return row


def notify_schedule_channel(session: Session, event_id: int) -> None:
    """``NOTIFY schedule_channel, '<event_id>'`` — TASARIM.md §7/§8. Postgres
    NOTIFY'ları çağıran transaction COMMIT olduğunda teslim eder; bu yüzden
    bu fonksiyonu çağıran taraf mutlaka ardından ``session.commit()``
    çağırmalıdır (bkz. ``emit_event``)."""
    session.execute(text("SELECT pg_notify('schedule_channel', :payload)"), {"payload": str(event_id)})


def emit_event(
    session: Session, *, event_type: str, course_id: int | None = None, payload: dict | None = None
) -> LiveEvent:
    """``record_live_event`` + ``notify_schedule_channel`` — motorun/kontrol
    katmanının HER olay üretiminde çağırdığı tek giriş noktası."""
    row = record_live_event(session, event_type=event_type, course_id=course_id, payload=payload)
    notify_schedule_channel(session, row.id)
    return row


def create_simulation_run(
    session: Session,
    *,
    mode: str,
    status: str,
    tick_interval_ms: int,
    manager_model_version_id: int,
    worker_model_version_id: int,
    config: dict | None = None,
) -> SimulationRun:
    row = SimulationRun(
        mode=mode,
        status=status,
        tick_interval_ms=tick_interval_ms,
        manager_model_version_id=manager_model_version_id,
        worker_model_version_id=worker_model_version_id,
        config=config or {},
        started_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def get_simulation_run(session: Session, run_id: int) -> SimulationRun | None:
    return session.get(SimulationRun, run_id)


def get_latest_simulation_run(session: Session) -> SimulationRun | None:
    return session.execute(select(SimulationRun).order_by(SimulationRun.id.desc()).limit(1)).scalar_one_or_none()


def set_simulation_run_status(session: Session, run_id: int, status: str) -> SimulationRun:
    row = session.get(SimulationRun, run_id)
    if row is None:
        raise ValueError(f"simulation_runs.id={run_id} bulunamadı")
    row.status = status
    if status == "stopped":
        row.stopped_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    return row
