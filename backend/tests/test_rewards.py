"""domain/rewards.py birim testleri — Faz 2 (eş. 32-35)."""

import pytest

from app.domain.rewards import (
    manager_capacity_violation_penalty,
    manager_course_partial_reward,
    manager_coverage_ratio,
    manager_overcapacity_penalty,
    manager_terminal_reward,
    worker_subtask_reward,
)

# Mevcut (over-öncesi) testlerde over terimini etkisizleştirmek için: omega3=0.0
# iken m_target'ın değeri sonucu etkilemez (0 * her şey = 0).
_NO_OVER = dict(m_target=1_000_000.0, omega3=0.0)


class TestManagerCoverageRatio:
    def test_basic_ratio(self):
        assert manager_coverage_ratio(80, 100) == pytest.approx(0.8)

    def test_full_coverage(self):
        assert manager_coverage_ratio(100, 100) == pytest.approx(1.0)

    def test_zero_total_is_zero_not_division_error(self):
        assert manager_coverage_ratio(0, 0) == 0.0


class TestManagerCapacityViolationPenalty:
    def test_no_violation_when_all_courses_meet_minimum(self):
        counts = {1: 60, 2: 70}
        assert manager_capacity_violation_penalty(counts, m_min=60) == 0.0

    def test_penalty_accumulates_for_undersized_courses(self):
        counts = {1: 30, 2: 60}
        # course 1: max(0, (60-30)/60) = 0.5 ; course 2: 0
        assert manager_capacity_violation_penalty(counts, m_min=60) == pytest.approx(0.5)

    def test_multiple_undersized_courses_sum(self):
        counts = {1: 30, 2: 0}
        # 0.5 + 1.0
        assert manager_capacity_violation_penalty(counts, m_min=60) == pytest.approx(1.5)


class TestManagerOvercapacityPenalty:
    """TASARIM.md §14.3.J — cap'in (eş. 33) ayna-simetriği: m_target ÜSTÜNE
    çıkan her kurs için orantılı bir ceza, m_min ALTINA düşen için değil."""

    def test_no_penalty_when_all_courses_at_or_under_target(self):
        counts = {1: 100, 2: 60}
        assert manager_overcapacity_penalty(counts, m_target=100) == 0.0

    def test_penalty_accumulates_for_oversized_courses(self):
        counts = {1: 103, 2: 100}
        # course 1: max(0, (103-100)/100) = 0.03 ; course 2: 0
        assert manager_overcapacity_penalty(counts, m_target=100) == pytest.approx(0.03)

    def test_multiple_oversized_courses_sum(self):
        counts = {1: 110, 2: 120}
        # 0.10 + 0.20
        assert manager_overcapacity_penalty(counts, m_target=100) == pytest.approx(0.30)


class TestManagerTerminalReward:
    def test_perfect_coverage_no_violation(self):
        reward = manager_terminal_reward(
            orders_used=100,
            orders_total=100,
            course_order_counts={1: 60, 2: 60},
            m_min=60,
            omega1=1.0,
            omega2=1.0,
            **_NO_OVER,
        )
        assert reward == pytest.approx(1.0)

    def test_penalty_reduces_reward(self):
        reward = manager_terminal_reward(
            orders_used=100,
            orders_total=100,
            course_order_counts={1: 30},
            m_min=60,
            omega1=1.0,
            omega2=2.0,
            **_NO_OVER,
        )
        # cov=1.0, cap=0.5 -> 1.0*1.0 - 2.0*0.5 = 0.0
        assert reward == pytest.approx(0.0)

    def test_omega_weights_are_applied(self):
        reward = manager_terminal_reward(
            orders_used=50,
            orders_total=100,
            course_order_counts={},
            m_min=60,
            omega1=3.0,
            omega2=5.0,
            **_NO_OVER,
        )
        assert reward == pytest.approx(3.0 * 0.5)

    def test_overcapacity_penalty_is_applied(self):
        reward = manager_terminal_reward(
            orders_used=100,
            orders_total=100,
            course_order_counts={1: 110},
            m_min=60,
            omega1=1.0,
            omega2=1.0,
            m_target=100.0,
            omega3=2.0,
        )
        # cov=1.0, cap=0 (110>=60), over=(110-100)/100=0.1 -> 1.0 - 0 - 2.0*0.1
        assert reward == pytest.approx(0.8)


class TestManagerCoursePartialReward:
    """docs/SONUCLAR.md §5 Faz A — kurs-bazlı ödül ayrıştırması.

    Kritik özellik: Σ_k manager_course_partial_reward(...) BİREBİR
    manager_terminal_reward(...) ile aynı olmalı (yaklaşık değil, kesin) —
    aksi halde ayrıştırma toplamı korumuyor demektir.
    """

    def test_matches_terminal_reward_for_single_course_no_transitions(self):
        # geçiş order'ı yok -> ana ve toplam sayaç aynı
        partial = manager_course_partial_reward(
            course_main_orders=80, course_total_orders=80, orders_total=100,
            m_min=60, omega1=1.0, omega2=1.0, **_NO_OVER,
        )
        terminal = manager_terminal_reward(
            orders_used=80, orders_total=100, course_order_counts={1: 80},
            m_min=60, omega1=1.0, omega2=1.0, **_NO_OVER,
        )
        assert partial == pytest.approx(terminal)

    def test_sum_over_courses_equals_terminal_reward_no_transitions(self):
        course_orders = {1: 60, 2: 30, 3: 100, 4: 0, 5: 45}
        orders_total = sum(course_orders.values())
        omega1, omega2, m_min = 1.0, 0.2, 60

        total_partial = sum(
            manager_course_partial_reward(
                course_main_orders=q, course_total_orders=q,
                orders_total=orders_total, m_min=m_min, omega1=omega1, omega2=omega2, **_NO_OVER,
            )
            for q in course_orders.values()
        )
        terminal = manager_terminal_reward(
            orders_used=orders_total,
            orders_total=orders_total,
            course_order_counts=course_orders,
            m_min=m_min,
            omega1=omega1,
            omega2=omega2,
            **_NO_OVER,
        )
        assert total_partial == pytest.approx(terminal)

    def test_sum_over_courses_equals_terminal_reward_with_transitions(self):
        # Her kursta bazı slotlar GEÇİŞ order'ı (cov'a dahil değil, cap'e dahil) —
        # bu, Faz A entegrasyon testinde yakalanan gerçek hatanın (ana/toplam
        # sayaç karışması) regresyon testidir.
        # (main, total) çiftleri kurs başına:
        courses = {1: (50, 60), 2: (20, 30), 3: (90, 100), 4: (0, 0), 5: (40, 45)}
        main_orders_total = sum(m for m, _ in courses.values())  # yalnızca ANA order'ların toplamı
        omega1, omega2, m_min = 1.0, 0.2, 60

        total_partial = sum(
            manager_course_partial_reward(
                course_main_orders=m, course_total_orders=t,
                orders_total=main_orders_total, m_min=m_min, omega1=omega1, omega2=omega2, **_NO_OVER,
            )
            for m, t in courses.values()
        )
        terminal = manager_terminal_reward(
            orders_used=sum(m for m, _ in courses.values()),
            orders_total=main_orders_total,
            course_order_counts={k: t for k, (_, t) in courses.items()},  # cap TOPLAM sayaçla hesaplanır
            m_min=m_min,
            omega1=omega1,
            omega2=omega2,
            **_NO_OVER,
        )
        assert total_partial == pytest.approx(terminal)

    def test_sum_over_courses_equals_terminal_reward_with_overcapacity(self):
        # AYNI eşitlik (Σ partial ≡ terminal) artik over terimi de AKTIFKEN
        # (omega3>0) korunuyor mu -- eş.34'ün üç-terimli hâlinin de toplamsal
        # kaldığının regresyon testi (bazı kurslar m_target'ı asıyor).
        courses = {1: (110, 110), 2: (30, 30), 3: (100, 100), 4: (0, 0), 5: (95, 105)}
        main_orders_total = sum(m for m, _ in courses.values())
        omega1, omega2, omega3, m_min, m_target = 1.0, 0.2, 0.1, 60, 100.0

        total_partial = sum(
            manager_course_partial_reward(
                course_main_orders=m, course_total_orders=t,
                orders_total=main_orders_total, m_min=m_min, omega1=omega1, omega2=omega2,
                m_target=m_target, omega3=omega3,
            )
            for m, t in courses.values()
        )
        terminal = manager_terminal_reward(
            orders_used=sum(m for m, _ in courses.values()),
            orders_total=main_orders_total,
            course_order_counts={k: t for k, (_, t) in courses.items()},
            m_min=m_min,
            omega1=omega1,
            omega2=omega2,
            m_target=m_target,
            omega3=omega3,
        )
        assert total_partial == pytest.approx(terminal)

    def test_undersized_course_is_penalized(self):
        partial = manager_course_partial_reward(
            course_main_orders=0, course_total_orders=0, orders_total=100,
            m_min=60, omega1=1.0, omega2=1.0, **_NO_OVER,
        )
        # cov_contribution=0, cap_contribution=1.0 -> 0 - 1.0
        assert partial == pytest.approx(-1.0)

    def test_zero_orders_total_is_zero_cov_not_division_error(self):
        partial = manager_course_partial_reward(
            course_main_orders=0, course_total_orders=0, orders_total=0,
            m_min=60, omega1=1.0, omega2=1.0, **_NO_OVER,
        )
        assert partial == pytest.approx(-1.0)  # cov=0 (guard), cap=1.0

    def test_oversized_course_incurs_over_penalty(self):
        partial = manager_course_partial_reward(
            course_main_orders=103, course_total_orders=103, orders_total=103,
            m_min=60, omega1=1.0, omega2=1.0, m_target=100.0, omega3=0.5,
        )
        # cov=1.0, cap=0 (103>=60), over=(103-100)/100=0.03 -> 1.0 - 0 - 0.5*0.03
        assert partial == pytest.approx(1.0 - 0.5 * 0.03)


class TestWorkerSubtaskReward:
    def test_failure_returns_negative_beta0(self):
        reward = worker_subtask_reward(
            transition_orders_used=5,
            success=False,
            r_s=10.0,
            beta0=4.0,
            beta1=1.0,
            beta2=2.0,
            soft_transition_limit=3,
        )
        assert reward == -4.0

    def test_success_under_soft_limit_no_extra_penalty(self):
        reward = worker_subtask_reward(
            transition_orders_used=2,
            success=True,
            r_s=10.0,
            beta0=4.0,
            beta1=1.0,
            beta2=2.0,
            soft_transition_limit=3,
        )
        # r_s - beta1*G - beta2*max(0, G-3) = 10 - 1*2 - 2*0 = 8
        assert reward == pytest.approx(8.0)

    def test_success_at_soft_limit_no_extra_penalty(self):
        reward = worker_subtask_reward(
            transition_orders_used=3,
            success=True,
            r_s=10.0,
            beta0=4.0,
            beta1=1.0,
            beta2=2.0,
            soft_transition_limit=3,
        )
        assert reward == pytest.approx(10.0 - 3.0 - 0.0)

    def test_success_over_soft_limit_applies_extra_penalty(self):
        reward = worker_subtask_reward(
            transition_orders_used=5,
            success=True,
            r_s=10.0,
            beta0=4.0,
            beta1=1.0,
            beta2=2.0,
            soft_transition_limit=3,
        )
        # r_s - beta1*G - beta2*max(0, G-3) = 10 - 5 - 2*2 = 1
        assert reward == pytest.approx(1.0)
