"""R^m (eş. 32-34), R^w (eş. 35).

Ödül katsayıları (ω1, ω2 — manager; r_s, β0, β1, β2 — worker) bu modülde
sabitlenmez: bunlar ``training_runs.hyperparams`` / ``training/configs/
default.yaml``'a ait RL hiperparametreleridir (TASARIM.md §3.10, §4),
``constraint_config``'in fiziksel kısıtlarından (Δw/Kz/m_min gibi) farklı
bir kategoridedir. Bu yüzden fonksiyonlar bu katsayıları çağırandan alır.

``soft_transition_limit`` istisnadır: makalede "at most three transition
orders" olarak açıkça belirtilen ve ``constraint_config`` tablosunda da
ayrı bir anahtar olarak tutulan (TASARIM.md §3.11, §12.2.3.1) tek somut
sayısal değerdir — bu yüzden eş. 35'teki sabit "3" yerine parametre olarak
geçirilir.

``m_target``/``omega3`` (eş. 34'ün TASARIM.md §14.3.J'de belgelenen
bilinçli uzantısı): makalenin eş. 11/33'ü ``m_max``'ı KESİN bir maskeleme
sınırı sayar, yumuşak bir bölge tanımlamaz. Bu modül ``m_max``'ın kendisini
HİÇ bilmez (o salt ``action_mask``'in kullandığı fiziksel/sert bir sınırdır,
``constraint_config``'te kalır) — yalnızca ``m_target`` (yumuşak hedef,
``m_max``'tan küçük/eşit olması beklenir ama bu modülde denetlenmez) ve
``omega3`` (ceza ağırlığı) reward_weights'ten alınır; ``soft_transition_limit``
ile AYNI kategoridedir (fiziksel kısıt değil, salt bir ödül tercihi), bu
yüzden ``constraint_config``'e DEĞİL ``reward_weights``'e ait.
"""

from __future__ import annotations

from collections.abc import Mapping


def manager_coverage_ratio(orders_used: int, orders_total: int) -> float:
    """cov = Q_used / Q_max — eş. 32."""
    if orders_total <= 0:
        return 0.0
    return orders_used / orders_total


def manager_capacity_violation_penalty(course_order_counts: Mapping[int, int], m_min: int) -> float:
    """cap = Σ_{k∈Ω} max(0, (m_min − Q_k)/m_min) — eş. 33."""
    return sum(max(0.0, (m_min - count) / m_min) for count in course_order_counts.values())


def manager_overcapacity_penalty(course_order_counts: Mapping[int, int], m_target: float) -> float:
    """over = Σ_{k∈Ω} max(0, (Q_k − m_target)/m_target) — cap'in (eş. 33) ayna-
    simetriği, TASARIM.md §14.3.J. m_target, ``action_mask``'in kullandığı
    SERT ``m_max`` sınırından AYRIDIR (bu modül m_max'ı hiç bilmez) — yalnızca
    "burayı geçince biraz pahalanır" diyen yumuşak bir hedeftir; m_target'ın
    üzerine çıkmak fizibilite açısından hâlâ tamamen serbesttir (ta ki gerçek/
    sert ``m_max``'a ulaşılana kadar), sadece ödül olarak ucuz değildir.
    """
    return sum(max(0.0, (count - m_target) / m_target) for count in course_order_counts.values())


def manager_course_partial_reward(
    *,
    course_main_orders: int,
    course_total_orders: int,
    orders_total: int,
    m_min: int,
    omega1: float,
    omega2: float,
    m_target: float,
    omega3: float,
) -> float:
    """eş. 34'ün (R^m = ω1·cov − ω2·cap − ω3·over) TEK bir kursa düşen payı.

    cov = Q_used/Q_max (eş. 32) yalnızca ANA (main) order'ları sayar
    (``orders_total`` da yalnızca ana order havuzunun toplamıdır — bkz.
    ``HotRollingEnv._main_orders_total``); bu yüzden bu fonksiyonun cov
    payı ``course_main_orders`` (kursa yerleşen ana order sayısı) kullanır.
    cap (eş. 33) ve over (TASARIM.md §14.3.J) ise ``m_min``/``m_target``
    kursun TOPLAM (ana+geçiş) slab kapasitesiyle kıyaslandığı için
    ``course_total_orders`` (ana+geçiş) kullanır — ``action_mask``'in
    ``progress.order_count``'u zaten hep bu toplamı temsil eder. Farklı
    sayaçlar kullanmak KASITLIDIR: aksi halde (geçiş order'larını cov'a
    dahil etmek) toplamı bozar.

    Bu ayrım doğruysa: cov toplamsaldır (Q_used = Σ_k course_main_orders_k)
    ve cap/over zaten kurslar üzerinden birer toplamdır (Σ_k), bu yüzden

        Σ_{k} manager_course_partial_reward(course_main_orders=..._k,
                                             course_total_orders=..._k, ...)
        ≡ manager_terminal_reward(orders_used=Σ_k course_main_orders_k, ...)

    birebir (yaklaşık değil, matematiksel olarak KESİN) eşittir — bkz.
    ``docs/SONUCLAR.md`` §5 Faz A / integration doğrulaması. Bu, epizot
    sonunda TEK bir seyrek terminal ödül yerine, HER kurs kapandığında
    manager'a o kursun kendi payını (aynı toplamı koruyarak) vermeyi
    mümkün kılar — kredi atama sorununu (manager'ın epizot başına ~10-15
    kararından yalnızca SONUNCUSUNUN ham sinyal alması) doğrudan hedefler.
    """
    cov_contribution = (course_main_orders / orders_total) if orders_total > 0 else 0.0
    cap_contribution = max(0.0, (m_min - course_total_orders) / m_min)
    over_contribution = max(0.0, (course_total_orders - m_target) / m_target)
    return omega1 * cov_contribution - omega2 * cap_contribution - omega3 * over_contribution


def manager_terminal_reward(
    *,
    orders_used: int,
    orders_total: int,
    course_order_counts: Mapping[int, int],
    m_min: int,
    omega1: float,
    omega2: float,
    m_target: float,
    omega3: float,
) -> float:
    """R^m = ω1·cov − ω2·cap − ω3·over — eş. 34 + TASARIM.md §14.3.J.

    Makale bunu "the manager's terminal reward" olarak tanımlar: manager
    epizodunun (kurs/kurslar tamamlandıktan) SONUNDA bir kez hesaplanan
    seyrek bir ödüldür. ``training/env.py`` (Faz 4) bu fonksiyonu yalnızca
    epizot sonunda çağırmalı, ara adımlarda 0 döndürmelidir.
    """
    cov = manager_coverage_ratio(orders_used, orders_total)
    cap = manager_capacity_violation_penalty(course_order_counts, m_min)
    over = manager_overcapacity_penalty(course_order_counts, m_target)
    return omega1 * cov - omega2 * cap - omega3 * over


def worker_subtask_reward(
    *,
    transition_orders_used: int,
    success: bool,
    r_s: float,
    beta0: float,
    beta1: float,
    beta2: float,
    soft_transition_limit: int,
) -> float:
    """R^w — eş. 35:

        R^w = r_s − β1·G − β2·max(0, G−3)   eğer F_s = 1 (başarı)
        R^w = −β0                            eğer F_s = 0 (başarısızlık)

    Yalnızca subtask (bir manager hedefine giden geçiş dizisi) tamamlandığında
    hesaplanır — ara transition-order seçimlerinde kullanılmaz
    (TASARIM.md §3.6: worker_decisions.reward "subtask bitince set edilir").
    """
    if not success:
        return -beta0
    g = transition_orders_used
    return r_s - beta1 * g - beta2 * max(0, g - soft_transition_limit)
