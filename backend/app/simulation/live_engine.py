"""asyncio loop — makalenin Figure 5 akışını gerçek Postgres satırları
üzerinde uygular. TASARIM.md §7 (Canlı Simülasyon Motoru — Hibrit Mod).

═══════════════════════════════════════════════════════════════════════════
Faz 5 tasarım kararları (gerekçeler için bkz. TASARIM.md §12.6)
═══════════════════════════════════════════════════════════════════════════

1. **``LiveEngine.step_once(session)`` = Figure 5'teki BİR karar noktası.**
   ``training/env.py``'nin ``step()``'iyle aynı granülerlik: bir çağrı, bir
   manager kararı YA DA bir worker kararı yürütür. Otonom modda art arda
   çağrılır (aralarda tick beklenir); PAUSED'ken ``/api/simulation/step``
   (Faz 6) tam olarak BİR çağrıya karşılık gelir.

2. **Crash-recovery yalnızca ``rolling_courses``+``course_slots``'tan
   ``CourseProgress``'i yeniden inşa eder (İlke 7); "faz" (manager mı worker
   mı sırada) YENİDEN İNŞA EDİLMEZ.** Motor her (yeniden) başlangıçta aktif
   kursun bir sonraki kararının HER ZAMAN bir manager kararı olduğunu
   varsayar. Bu güvenlidir: ``CourseProgress`` (dolayısıyla ``s_t``) DB'de
   zaten tutarlıdır, bir manager kararının ne olması gerektiği yalnızca BU
   state'e bakılarak belirlenir — yarım kalmış bir worker subtask'ının
   "hedefi" kaybedilir ama bu sadece o hedefe doğru zaten atılmış adımların
   "sünk maliyet" olarak kabul edilmesi anlamına gelir, hiçbir kısıt/tutarlılık
   ihlali yaratmaz. ``_failed_group_ids_this_course`` de aynı nedenle
   BELLEKTE tutulur (kalıcı değildir) — crash sonrası bir grup bir şans daha
   alabilir, bu yalnızca küçük bir verimlilik kaybıdır. Buna karşın
   ``_manager_attempts_this_course`` (→ ``manager_decisions.step_index``) ve
   ``_course_main_orders_used`` (→ R^m'nin kurs-bazlı ``cov`` payı) bir
   kursa "yeniden katılırken" DB'den (``count_manager_decisions``/
   ``count_main_slots``) RESEED EDİLİR — aksi halde step_index önceki
   kayıtlarla ÇAKIŞIR (bir regresyon testiyle yakalandı, bkz. §12.6).

3. **Kursun İLK yerleştirmesi için worker hiç çağrılmaz** — ``training/env.py``
   karar #4 ile TREN/SERVE PARİTESİ (İlke 1) için BİLİNÇLİ OLARAK aynen
   korunur (TASARIM.md §13'ün açık bıraktığı soru burada bu şekilde
   çözülmüştür — gerekçe: gerçek bir "ısıtma slabı" varlığı şemada
   MODELLENMEMİŞTİR, bu yüzden canlı sistemin farklı davranması için hiçbir
   ek bilgi kaynağı yoktur; farklı davranmak yalnızca train/serve skew
   yaratırdı).

4. **R^m'nin (eş. 34) "orders_total" paydası, sınırsız/sürekli akan canlı
   havuzda bir "epizot" kavramı olmadığı için KURS-BAZLI pragmatik bir
   yaklaşımla hesaplanır** — bkz. ``_close_course``: o kursta yerleştirilen
   ana order sayısı + o an havuzda kalan (tüketilmemiş) toplam ana order
   sayısı. Bu, canlıda ARTIK EĞİTİM YAPILMADIĞI (İlke: "canlıda keşif yoktur"
   — greedy çıkarım, gradyan güncellemesi YOK) için sadece gözlem/loglama
   amaçlıdır (``manager_decisions.reward`` sütunu).

5. **Olay granülerliği: DB satırı başına değil, KARAR başına ``live_events``.**
   Bir manager kararı 30-70 order'lık bir grubu TEK seferde yerleştirebilir;
   bunun için 30-70 ayrı ``slab_placed`` olayı YAYINLAMAK (a) demo/izleme
   UX'i açısından anlamsız gürültü üretir (b) şemanın zaten ayrı bir
   ``main_group_selected``/``transition_selected`` tipi tanımlamasıyla
   ÇELİŞİR. Bu yüzden: manager'ın doğrudan/worker-sonrası yerleştirmeleri
   ``main_group_selected``, worker'ın her tekil geçiş seçimi
   ``transition_selected`` olarak yayınlanır; ayrı bir ``slab_placed`` olayı
   Faz 5'te YAYINLANMAZ (şema hâlâ izin verir, ileride Faz 7 gerçek zamanlı
   bir "kurs dolum animasyonu" isterse eklenebilir).

6. **``max_manager_steps_per_course``/``max_worker_steps_per_subtask``**
   (sonsuz döngü korumaları, fiziksel kısıt DEĞİL) ``model_versions``'a hiç
   yazılmamış training-only hiperparametrelerdir (bkz. ``train.py``'nin
   ``hyperparams_dict``'i) — bu yüzden ``training/configs/default.yaml``
   dosyasından DOĞRUDAN (kod olarak DEĞİL, salt veri olarak) okunur; bu,
   ``app.training.*`` modüllerini import ETMEZ, yalnızca aynı YAML dosyasını
   ikinci kez okur (``config_synthetic.yaml``'ın seed_db.py+env.py arasında
   paylaşılmasıyla aynı örüntü).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH as DEFAULT_SYNTHETIC_CONFIG_PATH
from app.data_generation.generator import SyntheticConfig, generate_batch, load_synthetic_config
from app.db import crud
from app.db.base import SessionLocal
from app.db.crud import load_constraint_config
from app.db.models import MainProductGroup, RollingCourse, SlabOrder
from app.domain import action_mask, rewards, state_builder, transition_rules
from app.domain.dto import OrderAttributes
from app.simulation import control
from app.simulation.inference import ActiveModels, load_active_models
from app.simulation.notifier import LiveEventNotifier

logger = logging.getLogger(__name__)

_DEFAULT_TRAIN_CONFIG_PATH = Path(__file__).resolve().parents[1] / "training" / "configs" / "default.yaml"
_PAUSED_POLL_TIMEOUT_S = 5.0


class Phase(Enum):
    """``training/env.py``'nin ``DecisionKind``'inin bu sürece özgü karşılığı
    — kasıtlı olarak YENİDEN TANIMLANDI (İTHAL EDİLMEDİ), çünkü
    ``app.training`` paketi "API/canlı sürece hiç import edilmez" (TASARIM.md
    §4). İki değerli bir enum'u iki kez yazmak, İlke 1'in hedeflediği asıl
    riski (maskeleme/state/reward mantığının SAPMASI) hiç taşımaz."""

    MANAGER = "manager"
    WORKER = "worker"


@dataclass(frozen=True, slots=True)
class LoopBounds:
    max_manager_steps_per_course: int
    max_worker_steps_per_subtask: int


def load_loop_bounds(path: str | Path = _DEFAULT_TRAIN_CONFIG_PATH) -> LoopBounds:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return LoopBounds(
        max_manager_steps_per_course=int(raw["max_manager_steps_per_course"]),
        max_worker_steps_per_subtask=int(raw["max_worker_steps_per_subtask"]),
    )


@dataclass
class _PendingSubtask:
    """Aktif bir manager→worker devrinin (handoff) bellek-içi state'i —
    bkz. modül-üstü karar #2: bu KASITLI olarak DB'ye YAZILMAZ."""

    manager_decision_id: int
    target_group_id: int
    target_first: OrderAttributes
    worker_attempts: int = 0


@dataclass(frozen=True, slots=True)
class StepOutcome:
    course_id: int | None
    detail: str
    course_closed: bool = False


class LiveEngine:
    """Tek bir ``simulation_runs`` oturumu boyunca yaşayan, kurs-içi bellek
    state'ini (``_pending``, deneme sayaçları) taşıyan orkestratör. DB
    erişimi SADECE ``db/crud.py`` üzerinden yapılır (TASARIM.md §1 ilke 1'in
    "tek kaynak" ruhunun DB katmanına yansıması)."""

    def __init__(self, *, models: ActiveModels, constraints: RollingConstraints, bounds: LoopBounds) -> None:
        self._models = models
        self._constraints = constraints
        self._bounds = bounds
        self._pending: _PendingSubtask | None = None
        self._manager_attempts_this_course = 0
        self._failed_group_ids_this_course: set[int] = set()
        self._course_main_orders_used = 0
        self._current_course_id: int | None = None

    def phase(self) -> Phase:
        return Phase.WORKER if self._pending is not None else Phase.MANAGER

    # ── genel API ──────────────────────────────────────────────────────

    def step_once(self, session: Session) -> StepOutcome:
        course = crud.get_active_course(session)
        if course is None:
            if not crud.load_available_groups(session, limit=1):
                return StepOutcome(course_id=None, detail="idle: havuzda uygun ana grup yok")
            course = crud.start_new_course(session, constraints=self._constraints)
            crud.emit_event(
                session,
                event_type="course_started",
                course_id=course.id,
                payload={"course_number": course.course_number},
            )

        if course.id != self._current_course_id:
            # "Yeni bir kursa geçtik" HEM gerçekten yeni bir kurs açıldığında
            # HEM de bu motor örneğinin bu kursu ilk kez gördüğü (ör.
            # crash-recovery sonrası devralınan aktif bir kurs) durumunda
            # tetiklenir -- bu yüzden sayaçlar sıfırdan DEĞİL, DB'nin o
            # kurs için zaten sahip olduğu satır sayısından reseed edilir
            # (TASARIM.md §12.6 karar #2: "faz" bellekte kalır ama
            # SAYAÇLARIN kendisi DB ile TUTARLI olmalı, aksi halde
            # step_index çakışır / cov hesabı yanlış kurs-toplamı kullanır).
            self._pending = None
            self._manager_attempts_this_course = crud.count_manager_decisions(session, course.id)
            self._failed_group_ids_this_course = set()
            self._course_main_orders_used = crud.count_main_slots(session, course.id)
            self._current_course_id = course.id

        if self.phase() is Phase.MANAGER:
            return self._manager_step(session, course)
        return self._worker_step(session, course)

    # ── manager tarafı ────────────────────────────────────────────────

    def _manager_step(self, session: Session, course: RollingCourse) -> StepOutcome:
        progress = crud.load_course_progress(session, course)
        # TASARIM.md §14.3.E: last_attributes/constraints geçen "yakınlık
        # sıralaması" denendi, bol ölçekte anlamlı gerileme ölçülünce FIFO'ya
        # geri alındı (bkz. transition_rules.sort_groups_by_proximity docstring).
        groups = crud.load_available_groups(
            session, limit=self._models.k_max, exclude_ids=self._failed_group_ids_this_course
        )
        raw_mask = action_mask.manager_action_mask(groups, progress)
        mask = [raw_mask[g.id] for g in groups] + [False] * (self._models.k_max - len(groups))
        eligible_ids = [g.id for g in groups if raw_mask[g.id]]

        vector = state_builder.build_manager_state(
            groups,
            reverse_width_capability=transition_rules.reverse_width_capability(course.first_main_group_placed),
            order_count=progress.order_count,
            course_index=course.course_number,
            last_attributes=progress.last_attributes,
        ).to_vector(self._models.k_max)

        # step_index'i HER ZAMAN (terminal karar dahil) artırıyoruz ki
        # course_id başına kesinlikle artan/benzersiz kalsın -- kapatma
        # kararı da manager'ın gerçek bir kararıdır (bkz. TASARIM.md §3.5:
        # "boş mask ... kursu sonlandırma kararına denk düşer"), önceki
        # gerçek seçimle AYNI step_index'i paylaşmamalı.
        has_action = any(mask) and self._manager_attempts_this_course < self._bounds.max_manager_steps_per_course
        self._manager_attempts_this_course += 1

        if not has_action:
            reward = self._close_course(session, course)
            decision = crud.record_manager_decision(
                session,
                course_id=course.id,
                step_index=self._manager_attempts_this_course,
                vector=vector,
                eligible_group_ids=eligible_ids,
                selected_group_id=None,
                reward=reward,
                model_version_id=self._models.manager_model_version_id,
            )
            self._current_course_id = None  # bir sonraki step_once yeni/varsa bir sonraki kursu başlatır
            return StepOutcome(
                course_id=course.id, detail=f"kurs kapandı (manager_decision={decision.id})", course_closed=True
            )

        action_idx = self._models.manager_agent.select_action(vector, mask, greedy=True)
        selected = groups[action_idx]

        decision = crud.record_manager_decision(
            session,
            course_id=course.id,
            step_index=self._manager_attempts_this_course,
            vector=vector,
            eligible_group_ids=eligible_ids,
            selected_group_id=selected.id,
            reward=0.0,  # semi-MDP: yalnızca kursu kapatan karar ödül taşır (training/env.py ile parite)
            model_version_id=self._models.manager_model_version_id,
        )

        transition_needed = progress.last_attributes is not None and transition_rules.is_transition_required(
            progress.last_attributes,
            selected.first,
            self._constraints,
            cumulative_length_mm=progress.cumulative_length_mm,
            reverse_events_in_zone=progress.reverse_width_events_count,
        )
        if not transition_needed:
            placed = self._place_group(session, course, group_id=selected.id)
            crud.emit_event(
                session,
                event_type="main_group_selected",
                course_id=course.id,
                payload={"manager_decision_id": decision.id, "group_id": selected.id, "placed_count": placed},
            )
            return StepOutcome(course_id=course.id, detail=f"grup {selected.id} doğrudan yerleştirildi ({placed})")

        transitions = crud.load_available_transitions(session, limit=self._models.p_max)
        w_mask_raw = action_mask.worker_action_mask(
            transitions, used_transition_order_ids=frozenset(), progress=progress, constraints=self._constraints
        )
        if not any(w_mask_raw.values()):
            self._failed_group_ids_this_course.add(selected.id)
            return StepOutcome(course_id=course.id, detail=f"grup {selected.id} ulaşılamaz (köprü adayı yok)")

        self._pending = _PendingSubtask(
            manager_decision_id=decision.id, target_group_id=selected.id, target_first=selected.first
        )
        return StepOutcome(course_id=course.id, detail=f"worker'a devredildi (hedef grup {selected.id})")

    # ── worker tarafı ─────────────────────────────────────────────────

    def _worker_step(self, session: Session, course: RollingCourse) -> StepOutcome:
        assert self._pending is not None
        pending = self._pending
        progress = crud.load_course_progress(session, course)
        transitions = crud.load_available_transitions(session, limit=self._models.p_max)
        raw_mask = action_mask.worker_action_mask(
            transitions, used_transition_order_ids=frozenset(), progress=progress, constraints=self._constraints
        )
        mask = [raw_mask[t.id] for t in transitions] + [False] * (self._models.p_max - len(transitions))
        eligible_ids = [t.id for t in transitions if raw_mask[t.id]]

        groups_visible = crud.load_available_groups(
            session, limit=self._models.k_max, exclude_ids=self._failed_group_ids_this_course
        )
        vector = state_builder.build_worker_state(
            transitions,
            groups_visible,
            used_transition_count=pending.worker_attempts,
            reverse_width_event_count=progress.reverse_width_events_count,
            reverse_width_capability=transition_rules.reverse_width_capability(course.first_main_group_placed),
            last_attributes=progress.last_attributes,
            target_attributes=pending.target_first,
        ).to_vector(k_max=self._models.k_max, p_max=self._models.p_max)

        action_idx = self._models.worker_agent.select_action(vector, mask, greedy=True)
        chosen = transitions[action_idx]
        pending.worker_attempts += 1

        order_row = crud.consume_transition_order(session, order_id=chosen.id)
        new_progress = self._apply_order_to_progress(session, course, order_row, role="transition")
        w = self._models.reward_weights

        reached = not transition_rules.is_transition_required(
            new_progress.last_attributes,
            pending.target_first,
            self._constraints,
            cumulative_length_mm=new_progress.cumulative_length_mm,
            reverse_events_in_zone=new_progress.reverse_width_events_count,
        )
        if reached:
            worker_reward = rewards.worker_subtask_reward(
                transition_orders_used=pending.worker_attempts,
                success=True,
                r_s=w["r_s"],
                beta0=w["beta0"],
                beta1=w["beta1"],
                beta2=w["beta2"],
                soft_transition_limit=self._constraints.soft_transition_limit,
            )
            crud.record_worker_decision(
                session,
                manager_decision_id=pending.manager_decision_id,
                course_id=course.id,
                step_index=pending.worker_attempts - 1,
                vector=vector,
                eligible_transition_ids=eligible_ids,
                selected_transition_order_id=chosen.id,
                success=True,
                reward=worker_reward,
                model_version_id=self._models.worker_model_version_id,
            )
            crud.emit_event(
                session,
                event_type="transition_selected",
                course_id=course.id,
                payload={"manager_decision_id": pending.manager_decision_id, "transition_order_id": chosen.id, "success": True},
            )
            placed = self._place_group(session, course, group_id=pending.target_group_id)
            crud.emit_event(
                session,
                event_type="main_group_selected",
                course_id=course.id,
                payload={
                    "manager_decision_id": pending.manager_decision_id,
                    "group_id": pending.target_group_id,
                    "placed_count": placed,
                },
            )
            self._pending = None
            return StepOutcome(course_id=course.id, detail=f"geçiş hedefe ulaştı, grup {pending.target_group_id} yerleşti")

        remaining_transitions = crud.load_available_transitions(session, limit=self._models.p_max)
        remaining_mask = action_mask.worker_action_mask(
            remaining_transitions, used_transition_order_ids=frozenset(), progress=new_progress, constraints=self._constraints
        )
        give_up = (not any(remaining_mask.values())) or pending.worker_attempts >= self._bounds.max_worker_steps_per_subtask

        if not give_up:
            crud.record_worker_decision(
                session,
                manager_decision_id=pending.manager_decision_id,
                course_id=course.id,
                step_index=pending.worker_attempts - 1,
                vector=vector,
                eligible_transition_ids=eligible_ids,
                selected_transition_order_id=chosen.id,
                success=None,
                reward=0.0,
                model_version_id=self._models.worker_model_version_id,
            )
            crud.emit_event(
                session,
                event_type="transition_selected",
                course_id=course.id,
                payload={"manager_decision_id": pending.manager_decision_id, "transition_order_id": chosen.id, "success": None},
            )
            return StepOutcome(course_id=course.id, detail="geçiş yerleşti, subtask devam ediyor")

        worker_reward = rewards.worker_subtask_reward(
            transition_orders_used=pending.worker_attempts,
            success=False,
            r_s=w["r_s"],
            beta0=w["beta0"],
            beta1=w["beta1"],
            beta2=w["beta2"],
            soft_transition_limit=self._constraints.soft_transition_limit,
        )
        crud.record_worker_decision(
            session,
            manager_decision_id=pending.manager_decision_id,
            course_id=course.id,
            step_index=pending.worker_attempts - 1,
            vector=vector,
            eligible_transition_ids=eligible_ids,
            selected_transition_order_id=chosen.id,
            success=False,
            reward=worker_reward,
            model_version_id=self._models.worker_model_version_id,
        )
        crud.emit_event(
            session,
            event_type="transition_selected",
            course_id=course.id,
            payload={"manager_decision_id": pending.manager_decision_id, "transition_order_id": chosen.id, "success": False},
        )
        self._failed_group_ids_this_course.add(pending.target_group_id)
        self._pending = None
        return StepOutcome(course_id=course.id, detail=f"subtask başarısız, grup {pending.target_group_id} bu kurs için elendi")

    # ── yerleştirme / ilerleme muhasebesi ────────────────────────────

    def _place_group(self, session: Session, course: RollingCourse, *, group_id: int) -> int:
        group_row = session.get(MainProductGroup, group_id)
        assert group_row is not None
        capacity_left = course.max_orders - course.order_count
        take = max(0, min(capacity_left, group_row.group_size))
        members = crud.consume_group_members(session, group_id=group_id, take=take)
        for order in members:
            self._apply_order_to_progress(session, course, order, role="main")
        self._course_main_orders_used += len(members)
        return len(members)

    def _apply_order_to_progress(
        self, session: Session, course: RollingCourse, order_row: SlabOrder, *, role: str
    ) -> action_mask.CourseProgress:
        progress = crud.load_course_progress(session, course)
        length = float(order_row.theoretical_rolling_length)
        prev = progress.last_attributes
        new_attrs = OrderAttributes(
            width_mm=float(order_row.width_mm),
            thickness_mm=float(order_row.thickness_mm),
            hardness=float(order_row.hardness),
            heating_temp_c=float(order_row.heating_temp_c),
        )
        is_reverse = prev is not None and transition_rules.is_reverse_width_step(prev.width_mm, new_attrs.width_mm)
        in_zone = transition_rules.in_reverse_zone(progress.cumulative_length_mm, self._constraints)
        new_reverse_count = progress.reverse_width_events_count + (1 if (is_reverse and in_zone) else 0)
        new_cumulative = progress.cumulative_length_mm + length

        crud.append_course_slot(
            session,
            course=course,
            slab_order=order_row,
            role=role,
            cumulative_length_mm=new_cumulative,
            reverse_width_events_count=new_reverse_count,
            is_reverse_width=is_reverse,
        )
        return action_mask.CourseProgress(
            order_count=course.order_count,
            max_orders=course.max_orders,
            cumulative_length_mm=new_cumulative,
            reverse_width_events_count=new_reverse_count,
            last_attributes=new_attrs,
        )

    def _close_course(self, session: Session, course: RollingCourse) -> float:
        remaining_pool = crud.sum_available_group_sizes(session)
        orders_total = self._course_main_orders_used + remaining_pool
        w = self._models.reward_weights
        # m_target/omega3 (TASARIM.md §14.3.J) bu değişiklikten ÖNCE eğitilmiş
        # checkpoint'lerin model_versions.hyperparams'ında YOK — omega3=0.0
        # varsayılanı "over" terimini etkisizleştirir (m_target'ın değeri o
        # zaman önemsizleşir), yani eski modeller eskisi gibi davranmaya devam
        # eder; yalnızca m_target/omega3 İÇEREN (yeni eğitilmiş) checkpoint'ler
        # yumuşak kapasite cezasını fiilen uygular.
        reward = rewards.manager_course_partial_reward(
            course_main_orders=self._course_main_orders_used,
            course_total_orders=course.order_count,
            orders_total=orders_total,
            m_min=course.min_orders,
            omega1=w["omega1"],
            omega2=w["omega2"],
            m_target=w.get("m_target", 0.0),
            omega3=w.get("omega3", 0.0),
        )
        status = crud.complete_course(session, course, m_min=course.min_orders)
        crud.emit_event(
            session,
            event_type=("course_completed" if status == "completed" else "course_failed"),
            course_id=course.id,
            payload={"order_count": course.order_count, "status": status, "reward": reward},
        )
        return reward


# ── otonom döngü (asyncio) ────────────────────────────────────────────


def _execute_and_commit(engine: LiveEngine, run_id: int) -> StepOutcome:
    """TASARIM.md §9.4'te bulunan bir çökme üzerine eklenen koruma: eş-zamanlı
    bir DB işlemi (ör. dashboard'daki "Sunuma Hazırla" — ``clear_pending_pool``)
    bu adımın ORTASINDA az önce görülen bir grubu/order'ı silerse (yarış
    durumu — iki AYRI süreç aynı DB üzerinde koordinasyonsuz çalışıyor,
    tam önlemek pahalı/karmaşık olurdu), ``IntegrityError`` (veya başka bir
    geçici DB hatası) TÜM ``live_engine`` sürecini ÇÖKERTİRDİ (2026-08-17'de
    canlı olarak gözlendi). Artık yalnızca BU adım atlanır, süreç ayakta
    kalır — bir sonraki tick'te havuz muhtemelen tutarlı bir durumdadır."""
    with SessionLocal() as session:
        try:
            outcome = engine.step_once(session)
            session.commit()
            return outcome
        except SQLAlchemyError:
            session.rollback()
            logger.exception(
                "adım atlandı — DB hatası (muhtemelen eş-zamanlı bir havuz sıfırlamasıyla yarış durumu), süreç ayakta kalıyor"
            )
            return StepOutcome(course_id=None, detail="adım atlandı (geçici DB hatası)")


async def run_loop(*, engine: LiveEngine, run_id: int, notifier: LiveEventNotifier) -> None:
    """``simulation_runs.status``'a göre otonom tick / duraklat / dur
    döngüsü. DB I/O senkron kalır (``SessionLocal`` + ``asyncio.to_thread``)
    — her atomik karar zaten tek/hızlı bir transaction'dır; ``asyncio``
    burada SADECE tick bekleme + kontrol-olayı uyanışı için kullanılır
    (İlke 8: basitlik önceliği — bu ölçekte tam async SQLAlchemy'ye geçmek
    gereksiz karmaşıklık katardı)."""
    while True:
        with SessionLocal() as session:
            run = crud.get_simulation_run(session, run_id)
        if run is None or run.status == "stopped":
            logger.info("simulation_run id=%s durduruldu, döngü sonlanıyor", run_id)
            return

        if run.status == "running":
            outcome = await asyncio.to_thread(_execute_and_commit, engine, run_id)
            logger.info("tick: %s", outcome.detail)
            await notifier.wait_for_event(timeout=max(0.05, run.tick_interval_ms / 1000))
            continue

        # paused: bir kontrol olayı bekle (manual_step veya resume/stop)
        event_id = await notifier.wait_for_event(timeout=_PAUSED_POLL_TIMEOUT_S)
        if event_id is None:
            continue
        event = await notifier.fetch_event(event_id)
        if event is not None and event.event_type == "manual_step":
            outcome = await asyncio.to_thread(_execute_and_commit, engine, run_id)
            logger.info("manuel adım: %s", outcome.detail)


async def watch_and_run(*, models: ActiveModels, constraints: RollingConstraints, bounds: LoopBounds) -> None:
    """Faz 6 entegrasyonu: API sürecinin (``POST /api/simulation/start``)
    oluşturduğu bir sonraki çalıştırılabilir ``simulation_runs`` satırını
    bekler ve sürer; o oturum ``stopped`` olduğunda bir sonrakini beklemeye
    döner. TASARIM.md §2'nin "iki ayrı process, aynı DB üzerinden konuşur"
    modelinin motor tarafı — motor kimin/neyin oturumu BAŞLATTIĞINA
    bakmaksızın sürekli ayakta kalır (``uvicorn app.main:app`` +
    ``python -m app.simulation.live_engine --watch`` birlikte ayağa
    kaldırılır).

    Aynı ``LiveEngine`` örneği ardışık oturumlar arasında YENİDEN
    KULLANILIR: kurs-içi state zaten ``course.id``'ye göre kendini
    sıfırlar (bkz. ``step_once``'daki kurs-değişimi bloğu) —
    ``simulation_runs.id``'nin motorun kendi state'i için hiçbir anlamı
    yoktur, yalnızca DB'nin "şu an sürülmesi gereken oturum" işaretidir.
    """
    engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)
    async with LiveEventNotifier() as notifier:
        while True:
            with SessionLocal() as session:
                run = crud.get_latest_simulation_run(session)
            if run is not None and run.status != "stopped":
                logger.info("simulation_run id=%d yakalandı, sürülüyor", run.id)
                await run_loop(engine=engine, run_id=run.id, notifier=notifier)
                continue
            await notifier.wait_for_event(timeout=_PAUSED_POLL_TIMEOUT_S)


async def background_order_generator(
    *, synthetic_config: SyntheticConfig, constraints: RollingConstraints, interval_s: float, seed: int | None
) -> None:
    """TASARIM.md §5 "canlı demo için opsiyonel özellik": arka planda düşük
    frekanslı sentetik order akışı. Varsayılan olarak KAPALIDIR
    (``--enable-order-stream``); testler ve deterministik demo koşuları
    bunsuz da tam işlevseldir."""
    rng = random.Random(seed)

    def _generate_and_insert() -> int:
        with SessionLocal() as session:
            batch = generate_batch(synthetic_config, constraints, rng)
            inserted = crud.insert_generated_batch(session, batch)
            crud.emit_event(session, event_type="order_generated", payload={"count": inserted})
            session.commit()
            return inserted

    while True:
        await asyncio.sleep(interval_s)
        inserted = await asyncio.to_thread(_generate_and_insert)
        logger.info("order stream: %d yeni order eklendi", inserted)


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Canlı çizelgeleme motoru (TASARIM.md §7)")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="kendi oturumunu AÇMAZ; Faz 6 API'sinin (POST /api/simulation/start) "
        "oluşturacağı bir sonraki oturumu bekleyip sürer (bkz. watch_and_run)",
    )
    parser.add_argument("--mode", choices=["autonomous", "manual", "hybrid"], default="hybrid")
    parser.add_argument("--tick-ms", type=int, default=None)
    parser.add_argument("--run-id", type=int, default=None, help="mevcut bir simulation_runs satırına katıl")
    parser.add_argument("--enable-order-stream", action="store_true")
    parser.add_argument("--order-stream-interval-s", type=float, default=20.0)
    parser.add_argument("--synthetic-config", type=str, default=str(DEFAULT_SYNTHETIC_CONFIG_PATH))
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with SessionLocal() as session:
        constraints = load_constraint_config(session)
        models = load_active_models(session)
        run_id: int | None = None
        if not args.watch:
            if args.run_id is not None:
                run = crud.get_simulation_run(session, args.run_id)
                if run is None:
                    raise SystemExit(f"simulation_runs.id={args.run_id} bulunamadı")
            else:
                run = control.start(
                    session,
                    mode=args.mode,
                    tick_interval_ms=args.tick_ms or settings.default_tick_ms,
                    manager_model_version_id=models.manager_model_version_id,
                    worker_model_version_id=models.worker_model_version_id,
                    config={"seed": args.seed},
                )
            session.commit()
            run_id = run.id

    bounds = load_loop_bounds()

    def _order_stream_task() -> asyncio.Task | None:
        if not args.enable_order_stream:
            return None
        synthetic_config = load_synthetic_config(args.synthetic_config)
        return asyncio.create_task(
            background_order_generator(
                synthetic_config=synthetic_config,
                constraints=constraints,
                interval_s=args.order_stream_interval_s,
                seed=args.seed,
            )
        )

    async def _amain() -> None:
        tasks: list[asyncio.Task] = []
        stream_task = _order_stream_task()
        if stream_task is not None:
            tasks.append(stream_task)

        if args.watch:
            tasks.append(asyncio.create_task(watch_and_run(models=models, constraints=constraints, bounds=bounds)))
            await asyncio.gather(*tasks)
            return

        engine = LiveEngine(models=models, constraints=constraints, bounds=bounds)
        async with LiveEventNotifier() as notifier:
            tasks.append(asyncio.create_task(run_loop(engine=engine, run_id=run_id, notifier=notifier)))
            await asyncio.gather(*tasks)

    if args.watch:
        logger.info("live_engine watch modunda başladı — API'nin bir oturum açması bekleniyor")
    else:
        logger.info("live_engine başladı: run_id=%d mode=%s", run_id, args.mode)
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
