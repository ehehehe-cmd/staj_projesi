"""Sentetik order/grup üretici — TASARIM.md §5.

Tek çekirdek fonksiyon: ``generate_batch(config, constraints, rng)``. Bu
fonksiyon SAFTIR (DB yok, dosya I/O yok) — hem `training/env.py`'nin
`reset()` metodunda bellek-içi çağrılır (Faz 4, DB'siz hızlı simülasyon,
§1 ilke 2), hem `scripts/seed_db.py` tarafından gerçek PostgreSQL'e satır
eklemek için kullanılır (§12.4). İki kullanım da AYNI kod yolunu paylaşır.

Tasarım kararı — dönüş tipi (bkz. TASARIM.md §12.4): §5, imzayı
``generate_batch(config, rng) -> (main_groups, transition_pool)`` olarak
tarif eder. Bu modül dönüş değerini ``GeneratedBatch`` adlı küçük bir
dataclass'a genişletti çünkü ``scripts/seed_db.py``'nin ``slab_orders``
tablosuna TÜM bireysel order'ları (yalnızca her grubun first/last'ini
değil) yazması gerekiyor — ``MainGroupDTO``'nun eş. 26 soyutlaması
(first/last/size) bu iş için yetersizdir. ``GeneratedBatch.orders`` ham
havuzu taşır; ``.main_groups``/``.transitions`` ise ``domain/grouping.py``
(Faz 2) çağrılarak üretilir — sınıflandırma mantığı burada TEKRAR
YAZILMAZ (§1 ilke 1: tek kaynak kuralı).

Ardışık ana grupların ≤ ``soft_transition_limit`` geçiş order'ıyla
köprülenebilir olması garantisi (§5: *"aksi halde worker hiçbir zaman
başarılı olamaz ve öğrenilecek bir politika kalmaz"*) iki adımda sağlanır:
``_bounded_step`` bir sonraki ana grup özniteliğini öncekinden en fazla
``(soft_transition_limit+1) × Δ`` uzaklıkta örnekler; ``_bridge_chain`` bu
iki nokta arasını, her adımı Δw/Δt/Δh/Δθ toleransı içinde kalan doğrusal
enterpolasyonlu bir zincirle doldurur.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.constraints import RollingConstraints
from app.domain.dto import (
    MainGroupDTO,
    OrderAttributes,
    SlabOrderDTO,
    TransitionOrderDTO,
    compute_theoretical_rolling_length,
)
from app.domain.grouping import classify_and_group

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config_synthetic.yaml"


@dataclass(frozen=True, slots=True)
class Range:
    min: float
    max: float

    def sample(self, rng: random.Random) -> float:
        return rng.uniform(self.min, self.max)


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    """``config_synthetic.yaml``'ın tip-güvenli karşılığı. Tüm sayısal
    aralıklar mühendislik tahminine dayalı YER TUTUCU'dur (bkz. YAML dosyası
    üstündeki yorum ve TASARIM.md §12.4)."""

    main_steel_grades: tuple[str, ...]
    transition_steel_grades: tuple[str, ...]
    main_groups_per_course: Range
    group_size: Range
    main_width_mm: Range
    main_thickness_mm: Range
    main_hardness: Range
    main_heating_temp_c: Range
    within_batch_jitter_hardness: float
    within_batch_jitter_heating_temp_c: float
    slab_thickness_mm: Range
    slab_length_mm: Range
    slab_width_margin_mm: Range
    transition_width_mm: Range
    transition_thickness_mm: Range
    transition_hardness: Range
    transition_heating_temp_c: Range
    decoy_transition_count: Range

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "SyntheticConfig":
        def rng_of(key: str) -> Range:
            raw = values[key]
            return Range(min=float(raw["min"]), max=float(raw["max"]))  # type: ignore[index]

        jitter = values["within_batch_jitter"]
        return cls(
            main_steel_grades=tuple(values["main_steel_grades"]),  # type: ignore[arg-type]
            transition_steel_grades=tuple(values["transition_steel_grades"]),  # type: ignore[arg-type]
            main_groups_per_course=rng_of("main_groups_per_course"),
            group_size=rng_of("group_size"),
            main_width_mm=rng_of("main_width_mm"),
            main_thickness_mm=rng_of("main_thickness_mm"),
            main_hardness=rng_of("main_hardness"),
            main_heating_temp_c=rng_of("main_heating_temp_c"),
            within_batch_jitter_hardness=float(jitter["hardness"]),  # type: ignore[index]
            within_batch_jitter_heating_temp_c=float(jitter["heating_temp_c"]),  # type: ignore[index]
            slab_thickness_mm=rng_of("slab_thickness_mm"),
            slab_length_mm=rng_of("slab_length_mm"),
            slab_width_margin_mm=rng_of("slab_width_margin_mm"),
            transition_width_mm=rng_of("transition_width_mm"),
            transition_thickness_mm=rng_of("transition_thickness_mm"),
            transition_hardness=rng_of("transition_hardness"),
            transition_heating_temp_c=rng_of("transition_heating_temp_c"),
            decoy_transition_count=rng_of("decoy_transition_count"),
        )


def load_synthetic_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SyntheticConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SyntheticConfig.from_mapping(raw)


@dataclass(frozen=True, slots=True)
class GeneratedBatch:
    orders: tuple[SlabOrderDTO, ...]
    main_groups: tuple[MainGroupDTO, ...]
    transitions: tuple[TransitionOrderDTO, ...]


def generate_batch(
    config: SyntheticConfig,
    constraints: RollingConstraints,
    rng: random.Random,
) -> GeneratedBatch:
    """§5'in `generate_batch(config, rng) -> (main_groups, transition_pool)`
    olarak tarif ettiği fonksiyonun uygulaması (dönüş tipi genişletmesi için
    bkz. modül üstü docstring)."""
    orders: list[SlabOrderDTO] = []
    next_id = 1

    group_count = rng.randint(int(config.main_groups_per_course.min), int(config.main_groups_per_course.max))
    group_specs: list[tuple[str, OrderAttributes, int]] = []
    prev_attrs: OrderAttributes | None = None
    for _ in range(group_count):
        grade = rng.choice(config.main_steel_grades)
        attrs = _sample_main_spec(config, constraints, rng, prev_attrs)
        size = rng.randint(int(config.group_size.min), int(config.group_size.max))
        group_specs.append((grade, attrs, size))
        prev_attrs = attrs

    materialized_groups: list[list[SlabOrderDTO]] = []
    for grade, attrs, size in group_specs:
        group_orders: list[SlabOrderDTO] = []
        for _ in range(size):
            order = _materialize_order(next_id, grade, attrs, "main", config, rng)
            group_orders.append(order)
            next_id += 1
        orders.extend(group_orders)
        materialized_groups.append(group_orders)

    # Köprü zincirini grup ORTALAMASINDAN değil, sınırdaki GERÇEK (jitter'lı)
    # order'ların özniteliklerinden kurar — bkz. _bounded_step'in safety_margin
    # notu: bridge_chain grup ortalamasından interpolasyon yapsaydı, son
    # üyenin hardness/heating_temp jitter'ı toleransı ε kadar aşabilirdi.
    for prev_group, next_group in zip(materialized_groups, materialized_groups[1:]):
        bridge_grade = rng.choice(config.transition_steel_grades)
        prev_attrs = prev_group[-1].attributes
        next_attrs = next_group[0].attributes
        for attrs in _bridge_chain(prev_attrs, next_attrs, constraints):
            orders.append(_materialize_order(next_id, bridge_grade, attrs, "transition", config, rng))
            next_id += 1

    decoy_count = rng.randint(int(config.decoy_transition_count.min), int(config.decoy_transition_count.max))
    for _ in range(decoy_count):
        grade = rng.choice(config.transition_steel_grades)
        attrs = OrderAttributes(
            width_mm=config.transition_width_mm.sample(rng),
            thickness_mm=config.transition_thickness_mm.sample(rng),
            hardness=config.transition_hardness.sample(rng),
            heating_temp_c=config.transition_heating_temp_c.sample(rng),
        )
        orders.append(_materialize_order(next_id, grade, attrs, "transition", config, rng))
        next_id += 1

    main_groups, transitions = classify_and_group(orders, transition_grades=set(config.transition_steel_grades))
    return GeneratedBatch(orders=tuple(orders), main_groups=tuple(main_groups), transitions=tuple(transitions))


def _sample_main_spec(
    config: SyntheticConfig,
    constraints: RollingConstraints,
    rng: random.Random,
    prev: OrderAttributes | None,
) -> OrderAttributes:
    if prev is None:
        return OrderAttributes(
            width_mm=config.main_width_mm.sample(rng),
            thickness_mm=config.main_thickness_mm.sample(rng),
            hardness=config.main_hardness.sample(rng),
            heating_temp_c=config.main_heating_temp_c.sample(rng),
        )
    max_hops = constraints.soft_transition_limit + 1
    return OrderAttributes(
        width_mm=_bounded_step(prev.width_mm, constraints.delta_w, max_hops, config.main_width_mm, rng),
        thickness_mm=_bounded_step(prev.thickness_mm, constraints.delta_t, max_hops, config.main_thickness_mm, rng),
        # hardness/heating_temp_c: sınırdaki gerçek order (grubun son/ilk üyesi)
        # ±jitter kadar sapabilir (bkz. _materialize_order); güvenlik payı
        # olarak 2×jitter (her iki uçtaki olası en kötü durum) max_diff'ten
        # düşülür — böylece _bridge_chain her zaman gerçek (jitter'lı) uç
        # noktalar arasında ≤ soft_transition_limit adımla köprü kurabilir.
        hardness=_bounded_step(
            prev.hardness,
            constraints.delta_h,
            max_hops,
            config.main_hardness,
            rng,
            safety_margin=2 * config.within_batch_jitter_hardness,
        ),
        heating_temp_c=_bounded_step(
            prev.heating_temp_c,
            constraints.delta_theta,
            max_hops,
            config.main_heating_temp_c,
            rng,
            safety_margin=2 * config.within_batch_jitter_heating_temp_c,
        ),
    )


def _bounded_step(
    prev_value: float,
    delta: float,
    max_hops: int,
    value_range: Range,
    rng: random.Random,
    *,
    safety_margin: float = 0.0,
) -> float:
    """Bir sonraki ana grup özniteliğini ``prev_value``'dan en fazla
    ``max_hops * delta - safety_margin`` uzaklıkta örnekler — bu,
    ``_bridge_chain``'in en fazla ``max_hops - 1`` (== soft_transition_limit)
    ara order ile köprü kurabileceğini garanti eder. ``safety_margin``,
    grup sınırındaki gerçek (jitter'lı) order'ların spec'ten sapabileceği
    payı önceden rezerve eder (bkz. çağıran).
    """
    max_diff = max(0.0, delta * max_hops - safety_margin)
    lo = max(value_range.min, prev_value - max_diff)
    hi = min(value_range.max, prev_value + max_diff)
    if lo > hi:
        lo, hi = value_range.min, value_range.max
    return rng.uniform(lo, hi)


def _bridge_chain(
    prev: OrderAttributes,
    target: OrderAttributes,
    constraints: RollingConstraints,
) -> list[OrderAttributes]:
    """``prev`` → ``target`` arasını, her adımda eş. 17-20 (Δw/Δt/Δh/Δθ)
    toleransını koruyan, en fazla ``constraints.soft_transition_limit`` ara
    noktadan oluşan doğrusal-enterpolasyonlu bir zincirle doldurur.

    Yalnızca BOYUTSAL toleransı garanti eder — ters-genişlik-bölgesi
    kısıtları (eş. 21-25) bir order'ın içinde bulunacağı kursun gerçek
    ``cumulative_length_mm``'ine bağlı olduğundan (üretim anında henüz bir
    kursa yerleştirilmediği için bilinemez) burada UYGULANMAZ; asıl
    fizibilite denetimi, order'lar bir kursa yerleştirilirken
    ``action_mask.worker_action_mask`` (Faz 2) tarafından yapılır.
    """
    deltas = (constraints.delta_w, constraints.delta_t, constraints.delta_h, constraints.delta_theta)
    diffs = [abs(t - p) for p, t in zip(prev.as_tuple(), target.as_tuple())]
    hops_needed = [max(1, math.ceil(d / delta)) if delta > 0 else 1 for d, delta in zip(diffs, deltas)]
    hops = max(1, min(constraints.soft_transition_limit + 1, max(hops_needed)))

    chain: list[OrderAttributes] = []
    for step in range(1, hops):
        frac = step / hops
        values = tuple(p + frac * (t - p) for p, t in zip(prev.as_tuple(), target.as_tuple()))
        chain.append(OrderAttributes(*values))
    return chain


def _materialize_order(
    order_id: int,
    steel_grade: str,
    spec: OrderAttributes,
    order_class: str,
    config: SyntheticConfig,
    rng: random.Random,
) -> SlabOrderDTO:
    """Bir ``OrderAttributes`` hedefinden tam bir ``SlabOrderDTO`` üretir —
    slab boyutlarını (Wᵢ,Tᵢ,Lᵢ) örnekler ve lᵢ'yi (Table 2) hesaplar.

    Ana (main) order'larda width/thickness JITTER'SIZ, spec'ten AYNEN
    kopyalanır — çünkü ``grouping.classify_and_group`` (Faz 2) aynı grubun
    üyelerini `(steel_grade, width_mm, thickness_mm)` TAM eşleşmesiyle
    tespit eder (§1.2: "maintain stable dimensional parameters"); yalnızca
    hardness/heating_temp_c'de küçük bir batch-içi sapma modellenir.
    Geçiş (transition) order'ları zaten agregasyona uğramadığından
    (eş. 27) jitter uygulanmaz.
    """
    if order_class == "main":
        hardness = spec.hardness + rng.uniform(
            -config.within_batch_jitter_hardness, config.within_batch_jitter_hardness
        )
        heating_temp_c = spec.heating_temp_c + rng.uniform(
            -config.within_batch_jitter_heating_temp_c, config.within_batch_jitter_heating_temp_c
        )
    else:
        hardness = spec.hardness
        heating_temp_c = spec.heating_temp_c

    slab_width_mm = spec.width_mm + config.slab_width_margin_mm.sample(rng)
    slab_thickness_mm = config.slab_thickness_mm.sample(rng)
    slab_length_mm = config.slab_length_mm.sample(rng)

    return SlabOrderDTO(
        id=order_id,
        steel_grade=steel_grade,
        width_mm=spec.width_mm,
        thickness_mm=spec.thickness_mm,
        hardness=hardness,
        heating_temp_c=heating_temp_c,
        slab_width_mm=slab_width_mm,
        slab_thickness_mm=slab_thickness_mm,
        slab_length_mm=slab_length_mm,
        order_class=order_class,  # type: ignore[arg-type]
        theoretical_rolling_length=compute_theoretical_rolling_length(
            slab_width_mm=slab_width_mm,
            slab_thickness_mm=slab_thickness_mm,
            slab_length_mm=slab_length_mm,
            width_mm=spec.width_mm,
            thickness_mm=spec.thickness_mm,
        ),
    )
