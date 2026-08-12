"""Δw/Δt/Δh/Δθ kontrolü + ters-genişlik-bölgesi (reverse-width-zone) mantığı.

Makale eş. 17-25'in domain katmanındaki TEK uygulaması — hem `action_mask.py`
(canlı+eğitim ortak maskeleme) hem ileride `state_builder.py`'nin H_N
hesaplaması bu modülü kullanır (TASARIM.md §1 ilke 1).

Makale §1.2'nin metni: genişlik ilerlemesi kursun geneli boyunca
"bi-directional trapezoidal" bir örüntü izler — önce artan, sonra azalan
gradyan. Kz eşiği bu iki fazı ayırır:
  - C_{j,k} < Kz (eş. 23'ün b_{j,k}=1 hâli): "artış fazı" — küçük azalışlara
    (reverse event) Lr adede kadar izin verilir (eş. 24).
  - C_{j,k} ≥ Kz (b_{j,k}=0): "azalış fazı" — eş. 25 genişliğin KESİNLİKLE
    artmamasını zorunlu kılar.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.constraints import RollingConstraints
from app.domain.dto import MainGroupDTO, OrderAttributes

#: eş. 21'deki ε — Big-M formülasyonunun "kesin eşitsizlik" tespiti için
#: kullandığı küçük pozitif sabit (Table 2). constraint_config'in 9
#: anahtarından biri DEĞİLDİR (TASARIM.md §3.11) — fiziksel/iş kuralı değil,
#: salt sayısal-hassasiyet sabiti olduğu için config-driven değildir.
_EPSILON = 1e-6


def within_dimensional_tolerance(
    prev: OrderAttributes, candidate: OrderAttributes, constraints: RollingConstraints
) -> bool:
    """eş. 17-20: |Δw|≤Δw ∧ |Δt|≤Δt ∧ |Δh|≤Δh ∧ |Δθ|≤Δθ."""
    return (
        abs(prev.width_mm - candidate.width_mm) <= constraints.delta_w
        and abs(prev.thickness_mm - candidate.thickness_mm) <= constraints.delta_t
        and abs(prev.hardness - candidate.hardness) <= constraints.delta_h
        and abs(prev.heating_temp_c - candidate.heating_temp_c) <= constraints.delta_theta
    )


def is_transition_required(prev: OrderAttributes, target: OrderAttributes, constraints: RollingConstraints) -> bool:
    """Figure 5 "Transition required?" kararı: hedef zaten tolerans
    içindeyse worker'a hiç gerek yoktur.
    """
    return not within_dimensional_tolerance(prev, target, constraints)


def is_reverse_width_step(prev_width_mm: float, next_width_mm: float) -> bool:
    """eş. 21'in r_{j,k}=1 koşulu (z_{j,k}=z_{j,k+1}=1 sadeleştirmesiyle,
    domain katmanında iki pozisyon da zaten aday olduğu için bu terimler
    daima 1'dir): genişlik k'dan k+1'e küçüldüyse (ε payı ile) reverse event.
    """
    return (prev_width_mm - next_width_mm) >= _EPSILON


def in_reverse_zone(cumulative_length_mm: float, constraints: RollingConstraints) -> bool:
    """eş. 23'ün b_{j,k}=1 koşulu: C_{j,k} < Kz."""
    return cumulative_length_mm < constraints.kz


def reverse_width_budget_available(reverse_events_in_zone: int, constraints: RollingConstraints) -> bool:
    """eş. 24: Σ r_{j,k}·b_{j,k} ≤ Lr. Bölge içinde şimdiye kadar sayılan
    reverse event sayısı Lr'ye ulaştıysa yeni bir reverse'e izin yoktur.
    """
    return reverse_events_in_zone < constraints.lr


def width_step_is_feasible(
    *,
    prev_width_mm: float,
    next_width_mm: float,
    cumulative_length_mm: float,
    reverse_events_in_zone: int,
    constraints: RollingConstraints,
) -> bool:
    """eş. 21+23+24+25'in birleşik uygulaması: bir sonraki pozisyona
    ``next_width_mm`` yerleştirilmesi genişlik-yönü/ters-genişlik kurallarını
    ihlal eder mi?

    Not: eş. 17'deki |Δw|≤Δw sınırı bu fonksiyondan AYRI olarak
    ``within_dimensional_tolerance`` ile kontrol edilmelidir; bu fonksiyon
    yalnızca yön/bütçe (reverse-width) mantığını uygular.
    """
    reverse = is_reverse_width_step(prev_width_mm, next_width_mm)
    if in_reverse_zone(cumulative_length_mm, constraints):
        if not reverse:
            return True
        return reverse_width_budget_available(reverse_events_in_zone, constraints)
    # Bölge dışı: eş. 25 → w_{j,k} - w_{j,k+1} >= 0, yani artış yasak.
    return next_width_mm <= prev_width_mm + _EPSILON


def dimensional_distance(prev: OrderAttributes, candidate: OrderAttributes, constraints: RollingConstraints) -> float:
    """``within_dimensional_tolerance``'ın (eş. 17-20) ikili (True/False)
    sonucunu SIRALANABİLİR bir skora genişletir — TASARIM.md §14.3.E:
    Δw/Δt/Δh/Δθ ile normalize edilmiş toplam mesafe (kaç "tolerans genişliği"
    uzakta). Kısıt kontrolü YAPMAZ, yalnızca görünürlük sıralaması içindir
    (bkz. ``sort_groups_by_proximity``).
    """
    return (
        abs(prev.width_mm - candidate.width_mm) / constraints.delta_w
        + abs(prev.thickness_mm - candidate.thickness_mm) / constraints.delta_t
        + abs(prev.hardness - candidate.hardness) / constraints.delta_h
        + abs(prev.heating_temp_c - candidate.heating_temp_c) / constraints.delta_theta
    )


def sort_groups_by_proximity(
    groups: Sequence[MainGroupDTO], last_attributes: OrderAttributes | None, constraints: RollingConstraints
) -> list[MainGroupDTO]:
    """TASARIM.md §14.3.E: k_max penceresine hangi grupların gireceğini
    (FIFO/``ORDER BY id`` yerine) "şu anki ``last_attributes``'a en yakın"
    sırasına göre belirler. Hem ``training/env.py::_visible_groups`` hem
    ``db/crud.py::load_available_groups`` bu fonksiyonu TEK kaynak olarak
    çağırır (TASARIM.md §1 ilke 1 — train/serve parite).

    ``last_attributes is None`` (kurs başı, henüz bir referans nokta yok)
    ise sıralama YAPILMAZ, orijinal (çağıranın geçtiği, FIFO) sıra
    korunur — bu, "kurs başında worker hiç çağrılmaz" tasarım kararıyla
    (TASARIM.md §12.6 karar #3) tutarlıdır: ilk yerleştirme zaten
    doğrudandır, bir "yakınlık" kavramı henüz anlamlı değildir.
    """
    if last_attributes is None:
        return list(groups)
    return sorted(groups, key=lambda g: dimensional_distance(last_attributes, g.first, constraints))


def reverse_width_capability(first_main_group_placed: bool) -> bool:
    """H_N (durum vektörü özniteliği). Makale metni: "Equation (25) limits
    such operations to the first half of the rolling process – practically,
    before the first main product order group." TASARIM.md §3.3'teki
    ``rolling_courses.first_main_group_placed`` alanı bu pratik
    sadeleştirmenin canlı sistemdeki karşılığıdır.

    ÖNEMLİ: bu bayrak yalnızca DURUM VEKTÖRÜNDE (state feature, bkz.
    state_builder.py) kullanılır — asıl fizibilite denetimi daima
    ``width_step_is_feasible`` (Kz/cumulative_length tabanlı, eş. 23)
    üzerinden yapılır; H_N sadece ajana bir ipucu sağlar, maskelemeyi
    tek başına belirlemez.
    """
    return not first_main_group_placed
