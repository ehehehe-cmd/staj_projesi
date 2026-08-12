"""Domain katmanının paylaşılan veri taşıyıcıları (dataclass'lar).

TASARIM.md §4: bu modül hem offline eğitim (``training/env.py``) hem canlı
çıkarım motoru (``simulation/live_engine.py``) tarafından ortak kullanılır —
"tek kaynak" ilkesi (§1 ilke 1) gereği order/grup/geçiş-order temsili tek
yerde tanımlanır.

Referans makale ile eşleme:
- ``OrderAttributes``  → tekil bir order'ın (wᵢ, tᵢ, hᵢ, θᵢ) dörtlüsü;
  Nₖ'nin s_first/s_last bileşenleri (eş. 26), worker'ın sₜ/s_target'ı
  (eş. 29) ve transition order Mₚ'nin (eş. 27) ortak alt-yapısıdır.
- ``SlabOrderDTO``     → ham order havuzundaki tek bir slab order (Table 2:
  order i). ``slab_orders`` tablosunun domain-seviyesi karşılığı.
- ``MainGroupDTO``     → Nₖ = (s_{Nₖ,first}, s_{Nₖ,last}, L_{Nₖ}) soyutlaması
  (eş. 26). ``main_product_groups`` tablosunun domain karşılığı.
- ``TransitionOrderDTO`` → Mₚ = (wᵢ, tᵢ, hᵢ, θᵢ) (eş. 27) — tam bireysel
  öznitelik kümesini korur, agregasyona uğramaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OrderClass = Literal["main", "transition"]


@dataclass(frozen=True, slots=True)
class OrderAttributes:
    """Bir order'ın geçiş kısıtlarında (eş. 17-20) kullanılan dört sayısal
    özniteliği: genişlik, kalınlık, sertlik, ısıtma sıcaklığı.
    """

    width_mm: float
    thickness_mm: float
    hardness: float
    heating_temp_c: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.width_mm, self.thickness_mm, self.hardness, self.heating_temp_c)


@dataclass(frozen=True, slots=True)
class SlabOrderDTO:
    """``slab_orders`` satırının domain-seviyesi karşılığı (Table 2: order i).

    ``main_group_id`` yalnızca ``order_class == 'main'`` iken dolu olabilir
    (TASARIM.md §3.1) — ``transition`` sınıfındaki order'lar hiçbir gruba
    ait değildir, kendi başlarına ``TransitionOrderDTO``'ya dönüştürülür.
    """

    id: int
    steel_grade: str
    width_mm: float
    thickness_mm: float
    hardness: float
    heating_temp_c: float
    slab_width_mm: float
    slab_thickness_mm: float
    slab_length_mm: float
    order_class: OrderClass | None = None
    main_group_id: int | None = None
    theoretical_rolling_length: float | None = None

    @property
    def attributes(self) -> OrderAttributes:
        return OrderAttributes(
            width_mm=self.width_mm,
            thickness_mm=self.thickness_mm,
            hardness=self.hardness,
            heating_temp_c=self.heating_temp_c,
        )

    def rolling_length(self) -> float:
        """lᵢ = (Wᵢ·Tᵢ·Lᵢ)/(wᵢ·tᵢ) — Table 2. ``theoretical_rolling_length``
        zaten hesaplanmışsa (DB'den okunmuşsa) onu döndürür; yoksa yeniden
        hesaplar. TASARIM.md §3.1: bu değer "insert sırasında hesaplanır" —
        formülün TEK kaynağı burasıdır; seed script de bu metodu çağırır.
        """
        if self.theoretical_rolling_length is not None:
            return self.theoretical_rolling_length
        return compute_theoretical_rolling_length(
            slab_width_mm=self.slab_width_mm,
            slab_thickness_mm=self.slab_thickness_mm,
            slab_length_mm=self.slab_length_mm,
            width_mm=self.width_mm,
            thickness_mm=self.thickness_mm,
        )


def compute_theoretical_rolling_length(
    *,
    slab_width_mm: float,
    slab_thickness_mm: float,
    slab_length_mm: float,
    width_mm: float,
    thickness_mm: float,
) -> float:
    """lᵢ = (Wᵢ·Tᵢ·Lᵢ)/(wᵢ·tᵢ) — Table 2 (kütle korunumu: slab hacmi = haddelenmiş
    şerit hacmi). ``width_mm``/``thickness_mm`` sıfır olamaz (fiziksel olarak
    geçersiz order); domain katmanı bunu doğrulamaz, üretici/seed katmanı
    sorumludur.
    """
    return (slab_width_mm * slab_thickness_mm * slab_length_mm) / (width_mm * thickness_mm)


@dataclass(frozen=True, slots=True)
class MainGroupDTO:
    """Nₖ = (s_{Nₖ,first}, s_{Nₖ,last}, L_{Nₖ}) — eş. 26.

    ``member_order_ids`` makalenin soyutlamasının (first/last/size) bir
    parçası DEĞİLDİR — state/action tasarımına sadece first/last/size
    yansıtılır (bkz. state_builder.py). Ancak canlı motorun/eğitim
    ortamının bir grup seçildiğinde tek tek order tüketebilmesi için grup
    üyelerinin kimliklerini bir yerde tutması gerekir; bu iç kullanım
    alanı burada taşınır ve dışa (state vektörüne) sızdırılmaz.
    """

    id: int
    steel_grade: str
    first: OrderAttributes
    last: OrderAttributes
    group_size: int
    initial_group_size: int
    member_order_ids: tuple[int, ...] = field(default=())

    def is_exhausted(self) -> bool:
        return self.group_size <= 0


@dataclass(frozen=True, slots=True)
class TransitionOrderDTO:
    """Mₚ = (wᵢ, tᵢ, hᵢ, θᵢ) — eş. 27. Ana gruplardan farklı olarak
    agregasyona uğramaz, tam bireysel öznitelik kümesini korur.
    """

    id: int
    steel_grade: str
    width_mm: float
    thickness_mm: float
    hardness: float
    heating_temp_c: float

    @property
    def attributes(self) -> OrderAttributes:
        return OrderAttributes(
            width_mm=self.width_mm,
            thickness_mm=self.thickness_mm,
            hardness=self.hardness,
            heating_temp_c=self.heating_temp_c,
        )
