"""Fiziksel/süreç kısıtlarının tip-güvenli taşıyıcısı.

TASARIM.md §1 ilke 6 ("config-driven kısıtlar"): Δw, Δt, Δh, Δθ, Kz, Lr,
m_min, m_max, soft_transition_limit kod içine sabit gömülmez. Bu modül
sadece değer taşıyıcı dataclass'ı tanımlar; canlı sistemde bu değerler
``constraint_config`` tablosundan (bkz. app/db/models.py ConstraintConfig),
eğitimde ise bir YAML dosyasından okunup burada tanımlanan şekle
(``RollingConstraints``) dönüştürülür.

İsimlendirme notu: DB ORM modeli de ``ConstraintConfig`` adını taşıyor
(app/db/models.py) — bu dataclass'a bilinçli olarak farklı bir isim
(``RollingConstraints``) verildi ki iki modül birlikte import edildiğinde
isim çakışması olmasın.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

#: constraint_config tablosundaki 9 anahtarın tamamı (TASARIM.md §3.11 / §12.2.3.1).
REQUIRED_KEYS = (
    "delta_w",
    "delta_t",
    "delta_h",
    "delta_theta",
    "Kz",
    "Lr",
    "m_min",
    "m_max",
    "soft_transition_limit",
)


@dataclass(frozen=True, slots=True)
class RollingConstraints:
    """Makalenin Tablo 2'sindeki Δw, Δt, Δh, Δθ, Kz, Lr, m_min, m_max
    ve soft_transition_limit (=3, eş. 35) değerlerinin tek taşıyıcısı.

    Faz 1'de ``constraint_config`` tablosuna seed edilen sayısal değerler
    mühendislik tahminine dayalı YER TUTUCU'dur (bkz. TASARIM.md §12.2.3.1)
    — bu dataclass sadece şekli sabitler, sayısal değerleri sabitlemez.
    """

    delta_w: float
    delta_t: float
    delta_h: float
    delta_theta: float
    kz: float
    lr: int
    m_min: int
    m_max: int
    soft_transition_limit: int

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> "RollingConstraints":
        """``{key: value}`` biçimindeki bir eşlemeden (DB satırları ya da
        YAML'dan yüklenmiş dict) inşa eder. Hem canlı sistem (DB'den okunan
        ``constraint_config`` satırları) hem eğitim (YAML) aynı yolu kullanır.
        """
        missing = [k for k in REQUIRED_KEYS if k not in values]
        if missing:
            raise ValueError(f"RollingConstraints için eksik anahtar(lar): {missing}")
        return cls(
            delta_w=float(values["delta_w"]),
            delta_t=float(values["delta_t"]),
            delta_h=float(values["delta_h"]),
            delta_theta=float(values["delta_theta"]),
            kz=float(values["Kz"]),
            lr=int(values["Lr"]),
            m_min=int(values["m_min"]),
            m_max=int(values["m_max"]),
            soft_transition_limit=int(values["soft_transition_limit"]),
        )
