"""S^M_t (eş. 28) / S^W_t (eş. 29) vektör encoding, K_max/P_max padding.

Manager: S^M_t = (N, H_N, I_m, J, s_t)  — eş. 28 (bkz. yorum aşağıda).
Worker:  S^W_t = (M, N, I_W, H_M, H_N, s_t, s_target)  — eş. 29.

Tasarım notu — eş. 28'deki "I" sembolü hakkında (TASARIM.md §12.3.2'de
detaylandırılacak): referans PDF'te eş. 28, altı elemanlı bir demet olarak
render ediliyor: "S^M_t = (N, I, H_N, I_m, J, s_t)". Ancak izleyen düzyazı
paragrafı yalnızca N, H_N, I_m, J, s_t'yi tanımlıyor — ikinci eleman "I" hiç
açıklanmıyor (makalenin hiçbir yerinde bağımsız bir "I" durum bileşeni
tanımlanmamış). Bu, aynı paragrafta defalarca geçen "I_m" alt simgesinin
PDF metin çıkarımı sırasında ayrıştığı bir OCR/render artefaktı olarak
değerlendirildi. Bu modül, düzyazıda fiilen tanımlanan 5 bileşenle
uygulanmıştır. Worker durumunun (eş. 29) tüm 7 bileşeni düzyazıda birebir
tanımlı olduğu için orada böyle bir belirsizlik yoktur.

K_max (manager grup penceresi) ve P_max (worker geçiş-order penceresi) için
somut sayısal varsayılanlar bu modülde TANIMLANMAZ — TASARIM.md §13'te
"Faz 3'te sentetik veri istatistiklerine bakılarak belirlenecek" olarak
açıkça ertelenmiştir ve ayrıca TASARIM.md §4'e göre bunlar
``training/configs/default.yaml``'a ait hiperparametrelerdir, domain
katmanının sabit değeri değildir. Bu yüzden ``to_vector`` / ``*_mask``
metodları k_max/p_max'ı HER ZAMAN çağırandan parametre olarak alır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.dto import MainGroupDTO, OrderAttributes, TransitionOrderDTO

_ATTR_DIM = 4
_GROUP_FEATURE_DIM = 2 * _ATTR_DIM + 1  # first(4) + last(4) + size(1) = 9
_ZERO_ATTR: tuple[float, ...] = (0.0,) * _ATTR_DIM
_ZERO_GROUP: tuple[float, ...] = (0.0,) * _GROUP_FEATURE_DIM


@dataclass(frozen=True, slots=True)
class GroupFeature:
    """Nₖ'nin durum vektörüne yansıyan hâli: s_first(4) + s_last(4) + L_Nₖ(1)
    — eş. 26'nın doğrudan sayısal karşılığı.
    """

    first: OrderAttributes
    last: OrderAttributes
    size: int

    def as_tuple(self) -> tuple[float, ...]:
        return (*self.first.as_tuple(), *self.last.as_tuple(), float(self.size))


def _pad_groups(features: Sequence[GroupFeature], k_max: int) -> list[tuple[float, ...]]:
    truncated = features[:k_max]
    padded = [g.as_tuple() for g in truncated]
    padded.extend([_ZERO_GROUP] * (k_max - len(padded)))
    return padded


def _pad_attrs(attrs: Sequence[OrderAttributes], limit: int) -> list[tuple[float, ...]]:
    truncated = attrs[:limit]
    padded = [a.as_tuple() for a in truncated]
    padded.extend([_ZERO_ATTR] * (limit - len(padded)))
    return padded


@dataclass(frozen=True, slots=True)
class ManagerState:
    """S^M_t = (N, H_N, I_m, J, s_t) — eş. 28 (bkz. modül üstü yorum)."""

    available_groups: tuple[GroupFeature, ...]  # N
    reverse_width_capability: bool  # H_N
    order_count: int  # I_m
    course_index: int  # J
    last_attributes: OrderAttributes | None  # s_t

    def to_vector(self, k_max: int) -> list[float]:
        flat: list[float] = []
        for group_tuple in _pad_groups(self.available_groups, k_max):
            flat.extend(group_tuple)
        flat.append(1.0 if self.reverse_width_capability else 0.0)
        flat.append(float(self.order_count))
        flat.append(float(self.course_index))
        flat.extend(self.last_attributes.as_tuple() if self.last_attributes is not None else _ZERO_ATTR)
        return flat

    def group_mask(self, k_max: int) -> list[bool]:
        n = min(len(self.available_groups), k_max)
        return [True] * n + [False] * (k_max - n)


@dataclass(frozen=True, slots=True)
class WorkerState:
    """S^W_t = (M, N, I_W, H_M, H_N, s_t, s_target) — eş. 29."""

    available_transitions: tuple[OrderAttributes, ...]  # M
    available_groups: tuple[GroupFeature, ...]  # N
    used_transition_count: int  # I_W
    reverse_width_event_count: int  # H_M
    reverse_width_capability: bool  # H_N
    last_attributes: OrderAttributes | None  # s_t
    target_attributes: OrderAttributes  # s_target

    def to_vector(self, *, k_max: int, p_max: int) -> list[float]:
        flat: list[float] = []
        for attr_tuple in _pad_attrs(self.available_transitions, p_max):
            flat.extend(attr_tuple)
        for group_tuple in _pad_groups(self.available_groups, k_max):
            flat.extend(group_tuple)
        flat.append(float(self.used_transition_count))
        flat.append(float(self.reverse_width_event_count))
        flat.append(1.0 if self.reverse_width_capability else 0.0)
        flat.extend(self.last_attributes.as_tuple() if self.last_attributes is not None else _ZERO_ATTR)
        flat.extend(self.target_attributes.as_tuple())
        return flat

    def transition_mask(self, p_max: int) -> list[bool]:
        n = min(len(self.available_transitions), p_max)
        return [True] * n + [False] * (p_max - n)


def build_manager_state(
    groups: Sequence[MainGroupDTO],
    *,
    reverse_width_capability: bool,
    order_count: int,
    course_index: int,
    last_attributes: OrderAttributes | None,
) -> ManagerState:
    features = tuple(GroupFeature(first=g.first, last=g.last, size=g.group_size) for g in groups)
    return ManagerState(
        available_groups=features,
        reverse_width_capability=reverse_width_capability,
        order_count=order_count,
        course_index=course_index,
        last_attributes=last_attributes,
    )


def build_worker_state(
    transitions: Sequence[TransitionOrderDTO],
    groups: Sequence[MainGroupDTO],
    *,
    used_transition_count: int,
    reverse_width_event_count: int,
    reverse_width_capability: bool,
    last_attributes: OrderAttributes | None,
    target_attributes: OrderAttributes,
) -> WorkerState:
    transition_attrs = tuple(t.attributes for t in transitions)
    group_features = tuple(GroupFeature(first=g.first, last=g.last, size=g.group_size) for g in groups)
    return WorkerState(
        available_transitions=transition_attrs,
        available_groups=group_features,
        used_transition_count=used_transition_count,
        reverse_width_event_count=reverse_width_event_count,
        reverse_width_capability=reverse_width_capability,
        last_attributes=last_attributes,
        target_attributes=target_attributes,
    )
