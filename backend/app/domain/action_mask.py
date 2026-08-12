"""Manager & worker aksiyon maskeleme (eş. 8-25 + transition_rules).

Makale §2.2.5 "Constraint-driven action masking":
  - Manager seviyesi: yalnızca UNIQUENESS/kapasite (eş. 8-11) — tükenmiş
    (group_size=0) ya da kurs kapasitesi (m_max) dolmuş gruplar maskelenir.
    Geçiş fizibilitesi manager maskesinde KONTROL EDİLMEZ ("the manager
    filters current order information... to generate the target"; asıl
    fizibilite sorumluluğu worker'a aittir — bu, hiyerarşik ayrıştırmanın
    tam amacıdır).
  - Worker seviyesi: hem TÜKETİM maskesi (bu episotta zaten kullanılmış
    geçiş order'ları, eş. 8) hem FİZİBİLİTE maskesi (eş. 17-25) uygulanır.
    "Consequently, all actions that the worker can choose from are
    guaranteed to be locally feasible with respect to the MILP model."
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from app.core.constraints import RollingConstraints
from app.domain import transition_rules
from app.domain.dto import MainGroupDTO, OrderAttributes, TransitionOrderDTO


@dataclass(frozen=True, slots=True)
class CourseProgress:
    """Maskeleme için gereken kurs-içi ilerleme bilgisi. TASARIM.md §1
    ilke 7 (crash-recovery) ile aynı alanlar — ``rolling_courses`` +
    ``course_slots`` tablolarından doğrudan yeniden inşa edilebilir olacak
    şekilde tasarlandı.
    """

    order_count: int  # I_m
    max_orders: int  # m_max (kursun snapshot'ı)
    cumulative_length_mm: float  # C_j,k
    reverse_width_events_count: int  # bölge-içi (Kz altı) kullanılmış reverse sayısı
    last_attributes: OrderAttributes | None  # s_t — kursta hiç order yoksa None


def manager_action_mask(
    groups: Sequence[MainGroupDTO],
    progress: CourseProgress,
) -> dict[int, bool]:
    """eş. 8-11: her grup id → seçilebilir mi.

    Boş mask (tüm değerler False, ya da ``groups`` boşsa boş dict) kursu
    sonlandırma kararına denk düşer (``manager_decisions.selected_group_id
    = NULL``, TASARIM.md §3.5).
    """
    has_capacity = progress.order_count < progress.max_orders
    return {group.id: has_capacity and not group.is_exhausted() for group in groups}


def worker_action_mask(
    transitions: Sequence[TransitionOrderDTO],
    *,
    used_transition_order_ids: AbstractSet[int],
    progress: CourseProgress,
    constraints: RollingConstraints,
) -> dict[int, bool]:
    """eş. 8 (tüketim) + eş. 17-25 (fizibilite): her geçiş order id →
    seçilebilir mi.

    ``progress.last_attributes`` ``None`` ise (kursta henüz hiç order
    yerleştirilmemiş — ör. kursun ilk kararı) fizibilite kontrolü
    atlanır ve tüketilmemiş her order seçilebilir kabul edilir; bu uç
    durumun canlı sistemde (ısıtma slabı bağlamı) tam olarak nasıl ele
    alınacağı Faz 3/5'te netleşecektir (bkz. TASARIM.md §12.3.3).
    """
    if progress.order_count >= progress.max_orders:
        return {t.id: False for t in transitions}

    last = progress.last_attributes
    mask: dict[int, bool] = {}
    for order in transitions:
        if order.id in used_transition_order_ids:
            mask[order.id] = False
            continue
        if last is None:
            mask[order.id] = True
            continue
        feasible = transition_rules.within_dimensional_tolerance(last, order.attributes, constraints)
        if feasible:
            feasible = transition_rules.width_step_is_feasible(
                prev_width_mm=last.width_mm,
                next_width_mm=order.width_mm,
                cumulative_length_mm=progress.cumulative_length_mm,
                reverse_events_in_zone=progress.reverse_width_events_count,
                constraints=constraints,
            )
        mask[order.id] = feasible
    return mask
