"""§2.2.2 gruplama metodu: ham order havuzu → ana ürün grubu / geçiş order sınıflandırması.

Makale (§2.2.2): "the selection of transition slabs is strictly confined to
specific steel grades, while all other grades are systematically classified
as main rolling products" ve "main rolling products exhibit pronounced batch
characteristics and maintain stable dimensional parameters" (§1.2).

Tasarım kararı (bkz. TASARIM.md §12.3.2): makale, hangi çelik kalitelerinin
"geçiş-uygun" sayılacağını ya da bir batch'in tam olarak hangi alanlarla
eşleştiğini sayısal olarak vermiyor (gerçek fabrika verisi ticari gizli).
Bu modül bu yüzden:
  1) hangi steel_grade değerlerinin geçiş sınıfına ait olduğunu ÇAĞIRANDAN
     (`transition_grades` parametresi) alır — kod içine sabit gömülmez
     (TASARIM.md §1 ilke 6 ruhuyla tutarlı, ama bu spesifik alan
     `constraint_config`'in 9 anahtarından biri değildir; Faz 3'te sentetik
     üretici konfigürasyonundan gelecektir),
  2) ana order'ları (steel_grade, width_mm, thickness_mm) eşleşen "batch"lere
     gruplar — aynı ürün spesifikasyonuna sahip ardışık/dağınık order'lar
     tek bir Nₖ'ye toplanır; grup içi first/last sırası girdi listesindeki
     görülme sırasıdır (eş. 26'daki "grubun iç sıralaması" için basit ve
     test edilebilir bir yorum).
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from app.domain.dto import MainGroupDTO, SlabOrderDTO, TransitionOrderDTO


def classify_and_group(
    orders: Sequence[SlabOrderDTO],
    *,
    transition_grades: AbstractSet[str],
) -> tuple[list[MainGroupDTO], list[TransitionOrderDTO]]:
    """Ham order havuzunu (N, M) çiftine ayırır: ana ürün grupları listesi
    ve geçiş order'ları listesi.

    ``MainGroupDTO.id`` burada 1'den başlayan yerel bir sayaçtır — DB'ye
    kalıcı yazım (kalıcı id ataması) çağıranın (seed script / training env)
    sorumluluğundadır; bu fonksiyon saf/DB'siz domain mantığıdır.
    """
    main_orders: list[SlabOrderDTO] = []
    transitions: list[TransitionOrderDTO] = []
    for order in orders:
        if order.steel_grade in transition_grades:
            transitions.append(
                TransitionOrderDTO(
                    id=order.id,
                    steel_grade=order.steel_grade,
                    width_mm=order.width_mm,
                    thickness_mm=order.thickness_mm,
                    hardness=order.hardness,
                    heating_temp_c=order.heating_temp_c,
                )
            )
        else:
            main_orders.append(order)

    batches: dict[tuple[str, float, float], list[SlabOrderDTO]] = {}
    batch_key_order: list[tuple[str, float, float]] = []
    for order in main_orders:
        key = (order.steel_grade, order.width_mm, order.thickness_mm)
        if key not in batches:
            batches[key] = []
            batch_key_order.append(key)
        batches[key].append(order)

    main_groups: list[MainGroupDTO] = []
    for group_id, key in enumerate(batch_key_order, start=1):
        members = batches[key]
        steel_grade, _width, _thickness = key
        main_groups.append(
            MainGroupDTO(
                id=group_id,
                steel_grade=steel_grade,
                first=members[0].attributes,
                last=members[-1].attributes,
                group_size=len(members),
                initial_group_size=len(members),
                member_order_ids=tuple(o.id for o in members),
            )
        )

    return main_groups, transitions
