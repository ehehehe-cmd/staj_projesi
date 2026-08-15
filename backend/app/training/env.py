"""``HotRollingEnv`` — bellek-içi, DB'siz HRL ortamı (TASARIM.md §1 ilke 2, §6).

Bu modül, makale §2.2 (Figure 4/5) akışının, ``domain/*`` (Faz 2) ve
``data_generation/generator.py`` (Faz 3) üzerine kurulu SAF bir orkestrasyon
katmanıdır. Hiçbir kısıt/state/reward mantığı burada TEKRAR YAZILMAZ —
yalnızca domain fonksiyonları çağrılır (TASARIM.md §1 ilke 1).

═══════════════════════════════════════════════════════════════════════════
Faz 4 tasarım kararları (ayrıntılı gerekçeler için bkz. TASARIM.md §12.5)
═══════════════════════════════════════════════════════════════════════════

1. **Epizot = birden çok kurs, PAYLAŞIMLI havuz.** Makalenin deneyleri 5
   haddeleme kursluk episotlar kullanıyor (§3.1.2, §3.3.1: "each test subset
   consists of 5 rolling courses"). Bu ortam, ``courses_per_episode`` adet
   ``generate_batch()`` çağrısını TEK bir paylaşımlı havuzda (ana gruplar +
   geçiş order'ları) birleştirir; bir kurs sırasında kısmen tüketilen bir
   grup (``main_product_groups.status='partially_used'``, TASARIM.md §3.2)
   sonraki kursa taşınabilir. Bu, canlı sistemin DB'de kalıcı/paylaşımlı
   havuz semantiğiyle (§1 ilke 3 çevresi) tutarlıdır ve train/serve skew'i
   önler (§1 ilke 1).

2. **"Kurs bitti mi?" kontrolü environment'ın kendisi tarafından yapılır,
   manager'ın ayrı bir aksiyonu DEĞİLDİR.** Figure 5, "Course finished?"i
   bir manager aksiyonu olarak değil, otomatik bir ortam kontrolü olarak
   çiziyor. Bu ortamda: ``action_mask.manager_action_mask`` boş/tamamen-False
   döndüğünde (kapasite dolu VEYA havuzda uygun grup kalmadı) kurs biter —
   ayrı bir "sonlandır" aksiyonu YOKTUR (TASARIM.md §3.5'in zaten öngördüğü
   "boş mask = sonlandırma kararı" ile birebir tutarlı).

3. **Manager bir grup seçtiğinde, o grubun TÜM kalan order'ları (kapasiteyle
   sınırlı) TEK seferde kursa yerleştirilir.** Makale, manager'ın "grup"
   granülaritesinde karar verdiğini vurguluyor (§2.2.2.1: "the framework
   implements an actions-mapping strategy... which selects entire order
   clusters rather than individual orders"). Manager tek tek order
   seçmiyor; bir grup seçildiğinde o grubun mevcut tüm üyeleri (kapasite izin
   verdiğince) ardı ardına yerleştirilir.

4. **Kurs başındaki (last_attributes=None) İLK grup için worker hiç
   çağrılmaz.** TASARIM.md §12.3.3.6/§13'ün açık bıraktığı ısıtma-slabı
   semantiği burada şöyle çözüldü: kursun ilk yerleştirmesi her zaman
   doğrudandır (ısıtma slabının kendisinin herhangi bir ana grupla uyumlu
   olduğu varsayılır) — bu YALNIZCA eğitim ortamı için geçerli bir
   basitleştirmedir, canlı sistem (Faz 5) bunu farklı çözebilir.

5. **Geçiş order'ları GLOBAL ve KALICI olarak tüketilir** (tek kullanımlık
   fiziksel slab — makale §2.2.4: "the system updates the state by
   nullifying all attributes of Mp, effectively marking it as consumed").
   Kurs sınırları arasında SIFIRLANMAZ; bu yüzden ``worker_action_mask``'e
   her zaman boş ``used_transition_order_ids`` geçilir (havuzdan fiilen
   silinen bir order zaten bir daha hiç görünmez).

6. **Genişlik-ters-yön (eş. 21-25) muhasebesi HER yerleştirilen order için
   güncellenir** (ana VEYA geçiş — eş. 22'nin C_j,k toplamı tüm i,l
   üzerinden). ``width_step_is_feasible`` FEZİBİLİTE KAPISI hem
   ``action_mask.worker_action_mask`` (worker adayları) HEM DE
   ``transition_rules.is_transition_required`` (bir grubun DOĞRUDAN/
   geçişsiz yerleştirilip yerleştirilemeyeceği kararı) üzerinden uygulanır.
   ÖNCEDEN yalnızca worker tarafında uygulanıyordu — TASARIM.md §12.3.3.5'in
   "manager fizibilite kontrolü yapmaz" kararına dayanarak DOĞRUDAN
   yerleştirme bu kapıdan hiç geçmiyordu. Bu, Δw/Δt/Δh/Δθ toleransı
   içindeki (worker gerektirmeyen) küçük sıçramaların eş. 25'in "Kz sonrası
   genişlik artamaz" kuralını sessizce atlamasına yol açıyordu — canlı
   veride çok sayıda kursun net yönünü (ilk→son slot) makalenin öngördüğü
   azalan yerine artan yapacak kadar sistemik bir etkiydi. Bu yüzden
   ``is_transition_required`` genişletildi: artık boyutsal tolerans İÇİNDE
   olsa bile yön kuralını ihlal eden bir hedef "transition gerekli" sayılır
   (worker'a devredilir; worker da bunu asla köprüleyemeyeceği için grup bu
   kurs için elenir) — DOĞRUDAN yerleştirme artık bu kapıdan bloklanabilir.

7. **Semi-MDP ödül ilişkilendirmesi (manager'ın seyrek/terminal ödülü).**
   R^m (eş. 34) epizot başına TEK bir skalerdir, ama manager epizot boyunca
   ÇOK kez karar verir. Standart DQN sparse-terminal-reward pratiğiyle:
   epizotun SON manager kararı reward=R^m, done=True alır; öncekiler
   reward=0, done=False. Bir manager kararı worker'a devredildiğinde
   (transition gerekiyorsa), bu manager geçişi worker subtask'ı sonuçlanana
   kadar "askıda" kalır — ``step()`` bu durumda 0 ile 2 arası
   ``Transition`` döndürebilir (bkz. ``StepResult``). Bu, feudal/options
   çerçevesindeki standart "manager'ın adımı worker'ın subtask'ı bitince
   sonuçlanır" yapısıdır.

8. **Worker subtask'ı kendi mini-epizodu gibi ele alınır** — eş. 35 sadece
   subtask SONUNDA (başarı ya da ``max_worker_steps_per_subtask``/mask-boş
   ile zorunlu başarısızlık) hesaplanır; ara adımlar reward=0, done=False.

9. **Başarısız bir worker subtask'ı, hedef grubu o KURS için geçici olarak
   manager'ın görüş alanından çıkarır** (``_failed_group_ids_this_course``)
   — aksi halde manager aynı ulaşılamaz grubu sonsuza dek yeniden
   seçebilirdi. Bir sonraki kursta (last_attributes sıfırlandığından) grup
   tekrar denenebilir hale gelir.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from app.core.constraints import RollingConstraints
from app.data_generation.generator import SyntheticConfig, generate_batch
from app.domain import action_mask, rewards, state_builder, transition_rules
from app.domain.action_mask import CourseProgress
from app.domain.dto import MainGroupDTO, OrderAttributes, SlabOrderDTO, TransitionOrderDTO


class DecisionKind(Enum):
    MANAGER = "manager"
    WORKER = "worker"


@dataclass(frozen=True, slots=True)
class RewardWeights:
    """eş. 34 (ω1, ω2) + eş. 35 (r_s, β0, β1, β2) + TASARIM.md §14.3.J
    (m_target, ω3 — yumuşak kurs-kapasitesi hedefi). Sayısal değerler
    makalede verilmiyor (bkz. modül-üstü yorum / TASARIM.md §12.2.2) —
    ``training/configs/default.yaml``'dan gelir.
    """

    omega1: float
    omega2: float
    r_s: float
    beta0: float
    beta1: float
    beta2: float
    m_target: float
    omega3: float


@dataclass(frozen=True, slots=True)
class Observation:
    kind: DecisionKind
    vector: list[float]
    mask: list[bool]


@dataclass(frozen=True, slots=True)
class Transition:
    """Bir ajanın (manager YA DA worker) TAMAMLANMIŞ bir kararının sonucu.

    ``next_observation`` KASITLI OLARAK burada YOKTUR — "sıradaki karar
    için ne gözlemleneceği" tek bir yerde, ``StepResult.next_observation``
    içinde tutulur (bkz. o alanın yorumu). Bir ``Transition`` ``done=False``
    ise, ``StepResult.next_observation`` HER ZAMAN o Transition'ın kendi
    ajanına ait bir sonraki gözlemdir (env'in state-machine'i bunu garanti
    eder: bir manager kararı doğrudan yerleştirmeyle bittiğinde bir sonraki
    şey her zaman bir manager gözlemidir; bir worker adımı devam ettiğinde
    bir sonraki şey her zaman bir worker gözlemidir) — bu yüzden çağıran
    (``train.py``), ``done=False`` olan transition için
    ``result.next_observation``'ı doğrudan kullanabilir.
    """

    kind: DecisionKind
    reward: float
    done: bool


@dataclass(frozen=True, slots=True)
class StepResult:
    """``env.step()``'in dönüşü.

    ``transitions``: bu çağrıda SONUÇLANAN (reward/done bilinen) 0-2 karar.
    Genelde 1'dir; worker bir subtask'ı bitirip hedef grubu yerleştirdiğinde
    2 olur (worker'ın kendi subtask sonucu + bu sonucun tetiklediği manager
    sonucu, bkz. modül-üstü yorum karar #7). Manager bir geçiş gerektiren
    grup seçtiğinde (worker'a devir) 0 olur — HİÇBİR karar henüz
    sonuçlanmamıştır, manager'ın kararı worker subtask'ı bitene kadar
    "askıda" kalır.

    ``next_observation``: bir SONRAKİ dış aksiyonun (``step()`` çağrısının)
    üzerinde çalışacağı TEK gözlem — ``episode_done`` iken (ve SADECE o
    zaman) ``None``'dır. Bu alan ``transitions`` listesinden BAĞIMSIZDIR
    (0 transition dönse bile dolu olabilir — devir/handoff durumu tam
    olarak budur).
    """

    transitions: tuple[Transition, ...]
    episode_done: bool
    next_observation: Observation | None
    info: dict


@dataclass
class _GroupState:
    id: int
    steel_grade: str
    first: OrderAttributes
    last: OrderAttributes
    initial_group_size: int
    remaining_ids: list[int]

    @property
    def group_size(self) -> int:
        return len(self.remaining_ids)

    def to_dto(self) -> MainGroupDTO:
        return MainGroupDTO(
            id=self.id,
            steel_grade=self.steel_grade,
            first=self.first,
            last=self.last,
            group_size=self.group_size,
            initial_group_size=self.initial_group_size,
            member_order_ids=tuple(self.remaining_ids),
        )


class HotRollingEnv:
    """Gymnasium-esintili ama iki-seviyeli (manager+worker) bir orkestrasyon
    sınıfı — tek bir sabit ``action_space``'e sahip klasik ``gymnasium.Env``
    arayüzüne birebir uymaz (HRL'nin doğası bunu gerektirmez, bkz.
    TASARIM.md §12.5 kararı #7); ``reset``/``step`` isimlendirmesi ve
    sözleşmesi (mask + vector içeren gözlemler, done bayrakları) bilinçli
    olarak gymnasium konvansiyonlarına benzetildi.
    """

    def __init__(
        self,
        *,
        synthetic_config: SyntheticConfig,
        constraints: RollingConstraints,
        reward_weights: RewardWeights,
        courses_per_episode: int,
        k_max: int,
        p_max: int,
        max_manager_steps_per_course: int = 20,
        max_worker_steps_per_subtask: int = 10,
    ) -> None:
        self._config = synthetic_config
        self._constraints = constraints
        self._weights = reward_weights
        self._courses_per_episode = courses_per_episode
        self._k_max = k_max
        self._p_max = p_max
        self._max_manager_steps_per_course = max_manager_steps_per_course
        self._max_worker_steps_per_subtask = max_worker_steps_per_subtask

        self._rng: random.Random | None = None
        self._orders_by_id: dict[int, SlabOrderDTO] = {}
        self._groups: list[_GroupState] = []
        self._transitions: dict[int, TransitionOrderDTO] = {}
        self._main_orders_total = 0

        self._course_index = 0
        self._course_order_counts: dict[int, int] = {}
        self._main_orders_used = 0
        self._course_main_orders_used = 0  # bkz. Faz A: cov'un per-kurs payı için (ana order'lar, geçiş HARİÇ)

        self._progress: CourseProgress = CourseProgress(0, 0, 0.0, 0, None)
        self._first_main_group_placed = False
        self._failed_group_ids_this_course: set[int] = set()
        self._manager_attempts_this_course = 0

        self._phase: DecisionKind | None = None
        self._pending_group: _GroupState | None = None
        self._subtask_orders_used = 0
        self._worker_attempts_this_subtask = 0

    # ── genel API ──────────────────────────────────────────────────────

    def reset(self, *, seed: int) -> Observation:
        self._rng = random.Random(seed)
        self._load_pool()
        self._course_index = 0
        self._course_order_counts = {}
        self._main_orders_used = 0
        self._start_course()
        episode_done, obs, _ = self._advance_to_next_decision()
        if episode_done or obs is None:
            raise RuntimeError(
                "HotRollingEnv.reset: epizot ilk manager kararından ÖNCE bitti "
                "— generator boş bir havuz üretti (beklenmiyor)."
            )
        return obs

    def step(self, action_index: int) -> StepResult:
        if self._phase is None:
            raise RuntimeError("HotRollingEnv.step: epizot zaten bitti, önce reset() çağrılmalı")
        if self._phase is DecisionKind.MANAGER:
            return self._manager_step(action_index)
        return self._worker_step(action_index)

    # ── kurs/havuz muhasebesi ─────────────────────────────────────────

    def _load_pool(self) -> None:
        assert self._rng is not None
        orders_by_id: dict[int, SlabOrderDTO] = {}
        groups: list[_GroupState] = []
        transitions: dict[int, TransitionOrderDTO] = {}
        next_group_id = 1
        next_order_id = 1

        for _ in range(self._courses_per_episode):
            batch = generate_batch(self._config, self._constraints, self._rng)
            id_offset = next_order_id - 1
            for order in batch.orders:
                remapped = replace(order, id=order.id + id_offset)
                orders_by_id[remapped.id] = remapped
            for group in batch.main_groups:
                groups.append(
                    _GroupState(
                        id=next_group_id,
                        steel_grade=group.steel_grade,
                        first=group.first,
                        last=group.last,
                        initial_group_size=group.initial_group_size,
                        remaining_ids=[mid + id_offset for mid in group.member_order_ids],
                    )
                )
                next_group_id += 1
            for t in batch.transitions:
                remapped_t = replace(t, id=t.id + id_offset)
                transitions[remapped_t.id] = remapped_t
            next_order_id += len(batch.orders)

        self._orders_by_id = orders_by_id
        self._groups = groups
        self._transitions = transitions
        self._main_orders_total = sum(g.initial_group_size for g in groups)

    def _start_course(self) -> None:
        self._progress = CourseProgress(
            order_count=0,
            max_orders=self._constraints.m_max,
            cumulative_length_mm=0.0,
            reverse_width_events_count=0,
            last_attributes=None,
        )
        self._first_main_group_placed = False
        self._failed_group_ids_this_course = set()
        self._manager_attempts_this_course = 0
        self._course_main_orders_used = 0

    def _advance_to_next_decision(self) -> tuple[bool, Observation | None, float]:
        """Mevcut kursta manager için hâlâ bir aksiyon var mı kontrol eder;
        yoksa kursu kapatır ve sıradakine (ya da epizot sonuna) geçer.

        Döner: (episode_done, sıradaki manager Observation'ı ya da None,
        biriken ödül). eş. 34 (R^m) kurslar üzerinden TOPLAMSAL olduğu için
        (bkz. ``domain/rewards.manager_course_partial_reward`` docstring'i,
        ``docs/SONUCLAR.md`` §5 Faz A), her kurs kapanışında R^m'in o kursa
        düşen payı HEMEN döndürülür (episode_done=False iken de) — epizot
        sonunda TEK seyrek terminal ödül yerine, manager'a epizot başına
        (courses_per_episode kadar) daha sık bir sinyal verilir. Birden
        fazla kurs art arda tek bu çağrıda kapanırsa (ör. bir kursun hiç
        uygun grubu yoksa), payları toplanıp TEK dönüşte biriktirilir.
        Toplamda (tüm kurslar boyunca) `manager_terminal_reward` ile
        BİREBİR aynı sonucu verir — yalnızca ZAMANLAMASI değişir.
        """
        accumulated_reward = 0.0
        while True:
            groups, mask = self._manager_groups_and_mask()
            has_action = any(mask) and self._manager_attempts_this_course < self._max_manager_steps_per_course
            if has_action:
                vector = self._manager_vector(groups)
                self._phase = DecisionKind.MANAGER
                return False, Observation(DecisionKind.MANAGER, vector, mask), accumulated_reward

            course_total_orders = self._progress.order_count
            self._course_order_counts[self._course_index] = course_total_orders
            accumulated_reward += rewards.manager_course_partial_reward(
                course_main_orders=self._course_main_orders_used,
                course_total_orders=course_total_orders,
                orders_total=self._main_orders_total,
                m_min=self._constraints.m_min,
                omega1=self._weights.omega1,
                omega2=self._weights.omega2,
                m_target=self._weights.m_target,
                omega3=self._weights.omega3,
            )
            self._course_index += 1
            if self._course_index >= self._courses_per_episode:
                self._phase = None
                return True, None, accumulated_reward
            self._start_course()

    # ── manager tarafı ────────────────────────────────────────────────

    def _visible_groups(self) -> list[MainGroupDTO]:
        """FIFO (ekleme sırası = id sırası). TASARIM.md §14.3.E: "yakınlık"
        sıralaması denendi (``transition_rules.sort_groups_by_proximity``) —
        hem sıfırdan-eğitim hem TAM yeniden eğitim sonrası bol ölçekte
        (courses_per_episode=60) anlamlı bir GERİLEME ölçüldü (t≈-4.03
        coverage), bu yüzden FIFO'ya geri alındı. Fonksiyonun kendisi
        ``domain/transition_rules.py``'de referans için duruyor.
        """
        visible = [g for g in self._groups if g.group_size > 0 and g.id not in self._failed_group_ids_this_course]
        return [g.to_dto() for g in visible[: self._k_max]]

    def _manager_groups_and_mask(self) -> tuple[list[MainGroupDTO], list[bool]]:
        groups = self._visible_groups()
        raw = action_mask.manager_action_mask(groups, self._progress)
        mask = [raw[g.id] for g in groups]
        mask += [False] * (self._k_max - len(mask))
        return groups, mask

    def _manager_vector(self, groups: Sequence[MainGroupDTO]) -> list[float]:
        state = state_builder.build_manager_state(
            groups,
            reverse_width_capability=transition_rules.reverse_width_capability(self._first_main_group_placed),
            order_count=self._progress.order_count,
            course_index=self._course_index,
            last_attributes=self._progress.last_attributes,
        )
        return state.to_vector(self._k_max)

    def _manager_step(self, action_index: int) -> StepResult:
        groups, mask = self._manager_groups_and_mask()
        if not (0 <= action_index < len(mask)) or not mask[action_index]:
            raise ValueError(f"geçersiz (maskelenmiş) manager aksiyonu: {action_index}")
        selected_dto = groups[action_index]
        selected = next(g for g in self._groups if g.id == selected_dto.id)
        self._manager_attempts_this_course += 1

        transition_needed = self._progress.last_attributes is not None and transition_rules.is_transition_required(
            self._progress.last_attributes,
            selected.first,
            self._constraints,
            cumulative_length_mm=self._progress.cumulative_length_mm,
            reverse_events_in_zone=self._progress.reverse_width_events_count,
        )

        if not transition_needed:
            self._place_group(selected)
            episode_done, next_obs, terminal_reward = self._advance_to_next_decision()
            t = Transition(DecisionKind.MANAGER, terminal_reward, episode_done)
            return StepResult((t,), episode_done, next_obs, self._episode_summary() if episode_done else {})

        self._pending_group = selected
        self._subtask_orders_used = 0
        self._worker_attempts_this_subtask = 0
        worker_transitions, worker_mask = self._worker_transitions_and_mask()

        if not any(worker_mask):
            # Havuzda bu hedefe köprü kurabilecek TEK bir aday bile yok —
            # worker'a hiç dönmeden (boş maskeyle bir "karar noktası" DIŞARI
            # VERMEDEN) bu grubu kurs için elenmiş sayarız. NOT:
            # ``_resolve_subtask_failure`` KULLANILMAZ — worker HİÇBİR
            # aksiyon almadığı için ona ait bir Transition üretmek, train.py
            # tarafında karşılığı olmayan (pending_worker=None) bir
            # replay-kaydı yazmaya çalışmak anlamına gelirdi. Yalnızca
            # manager'ın askıdaki kararı sonuçlanır (eş. 35 burada devreye
            # girmez, çünkü F_s tanımı gereği bir subtask'ın var olduğunu
            # varsayar — burada subtask hiç BAŞLAMAMIŞTIR).
            self._failed_group_ids_this_course.add(selected.id)
            self._pending_group = None
            episode_done, m_obs, m_reward = self._advance_to_next_decision()
            manager_t = Transition(DecisionKind.MANAGER, m_reward, episode_done)
            return StepResult((manager_t,), episode_done, m_obs, self._episode_summary() if episode_done else {})

        self._phase = DecisionKind.WORKER
        worker_vector = self._worker_vector(worker_transitions, selected.first)
        worker_obs = Observation(DecisionKind.WORKER, worker_vector, worker_mask)
        return StepResult((), False, worker_obs, {})

    # ── worker tarafı ─────────────────────────────────────────────────

    def _visible_transitions(self) -> list[TransitionOrderDTO]:
        return list(self._transitions.values())[: self._p_max]

    def _worker_transitions_and_mask(self) -> tuple[list[TransitionOrderDTO], list[bool]]:
        transitions = self._visible_transitions()
        raw = action_mask.worker_action_mask(
            transitions,
            used_transition_order_ids=frozenset(),
            progress=self._progress,
            constraints=self._constraints,
        )
        mask = [raw[t.id] for t in transitions]
        mask += [False] * (self._p_max - len(mask))
        return transitions, mask

    def _worker_vector(self, transitions: Sequence[TransitionOrderDTO], target: OrderAttributes) -> list[float]:
        groups_visible = self._visible_groups()
        state = state_builder.build_worker_state(
            transitions,
            groups_visible,
            used_transition_count=self._subtask_orders_used,
            reverse_width_event_count=self._progress.reverse_width_events_count,
            reverse_width_capability=transition_rules.reverse_width_capability(self._first_main_group_placed),
            last_attributes=self._progress.last_attributes,
            target_attributes=target,
        )
        return state.to_vector(k_max=self._k_max, p_max=self._p_max)

    def _worker_step(self, action_index: int) -> StepResult:
        assert self._pending_group is not None
        target = self._pending_group
        transitions, mask = self._worker_transitions_and_mask()
        if not (0 <= action_index < len(mask)) or not mask[action_index]:
            raise ValueError(f"geçersiz (maskelenmiş) worker aksiyonu: {action_index}")

        chosen_dto = transitions[action_index]
        chosen_order = self._orders_by_id[chosen_dto.id]
        self._apply_order_to_progress(chosen_order)
        del self._transitions[chosen_dto.id]
        self._subtask_orders_used += 1
        self._worker_attempts_this_subtask += 1

        reached = not transition_rules.is_transition_required(
            self._progress.last_attributes,
            target.first,
            self._constraints,
            cumulative_length_mm=self._progress.cumulative_length_mm,
            reverse_events_in_zone=self._progress.reverse_width_events_count,
        )

        if reached:
            return self._resolve_subtask_success(target)

        _, remaining_mask = self._worker_transitions_and_mask()
        give_up = (not any(remaining_mask)) or self._worker_attempts_this_subtask >= self._max_worker_steps_per_subtask
        if give_up:
            return self._resolve_subtask_failure(target)

        remaining, remaining_mask = self._worker_transitions_and_mask()
        vector = self._worker_vector(remaining, target.first)
        self._phase = DecisionKind.WORKER
        next_obs = Observation(DecisionKind.WORKER, vector, remaining_mask)
        worker_t = Transition(DecisionKind.WORKER, 0.0, False)
        return StepResult((worker_t,), False, next_obs, {})

    def _resolve_subtask_success(self, target: "_GroupState") -> StepResult:
        """eş. 35, F_s=1 dalı — subtask başarıyla tamamlandı: hedef grup
        kursa yerleştirilir ve manager'ın (bu subtask'a yol açan) askıdaki
        kararı burada sonuçlanır (bkz. TASARIM.md §12.5 karar #7)."""
        worker_reward = rewards.worker_subtask_reward(
            transition_orders_used=self._subtask_orders_used,
            success=True,
            r_s=self._weights.r_s,
            beta0=self._weights.beta0,
            beta1=self._weights.beta1,
            beta2=self._weights.beta2,
            soft_transition_limit=self._constraints.soft_transition_limit,
        )
        self._pending_group = None
        self._place_group(target)
        episode_done, m_obs, m_reward = self._advance_to_next_decision()
        worker_t = Transition(DecisionKind.WORKER, worker_reward, True)
        manager_t = Transition(DecisionKind.MANAGER, m_reward, episode_done)
        return StepResult((worker_t, manager_t), episode_done, m_obs, self._episode_summary() if episode_done else {})

    def _resolve_subtask_failure(self, target: "_GroupState") -> StepResult:
        """eş. 35, F_s=0 dalı — hedefe ulaşan fizibl bir zincir bulunamadı
        (deneme hakları tükendi VEYA daha ilk andan itibaren hiç aday
        yoktu, bkz. ``_manager_step``'teki erken kontrol). Hedef grup bu
        KURS için manager'ın görüş alanından çıkarılır (§12.5 karar #9)."""
        worker_reward = rewards.worker_subtask_reward(
            transition_orders_used=self._subtask_orders_used,
            success=False,
            r_s=self._weights.r_s,
            beta0=self._weights.beta0,
            beta1=self._weights.beta1,
            beta2=self._weights.beta2,
            soft_transition_limit=self._constraints.soft_transition_limit,
        )
        self._failed_group_ids_this_course.add(target.id)
        self._pending_group = None
        episode_done, m_obs, m_reward = self._advance_to_next_decision()
        worker_t = Transition(DecisionKind.WORKER, worker_reward, True)
        manager_t = Transition(DecisionKind.MANAGER, m_reward, episode_done)
        return StepResult((worker_t, manager_t), episode_done, m_obs, self._episode_summary() if episode_done else {})

    # ── yerleştirme / ilerleme muhasebesi ────────────────────────────

    def _place_group(self, group: _GroupState) -> None:
        capacity_left = self._constraints.m_max - self._progress.order_count
        take = max(0, min(capacity_left, group.group_size))
        for _ in range(take):
            order_id = group.remaining_ids.pop(0)
            order = self._orders_by_id[order_id]
            self._apply_order_to_progress(order)
            self._main_orders_used += 1
            self._course_main_orders_used += 1
        if group.group_size == 0:
            self._groups = [g for g in self._groups if g.id != group.id]
        self._first_main_group_placed = True

    def _apply_order_to_progress(self, order: SlabOrderDTO) -> None:
        """eş. 21-23'ün defter tutma (bookkeeping) kısmı — bkz. modül-üstü
        yorum karar #6: burada FEZİBİLİTE denetlenmez, sadece C_j,k ve
        bölge-içi reverse sayacı güncellenir.
        """
        length = order.rolling_length()
        prev = self._progress.last_attributes
        is_reverse = prev is not None and transition_rules.is_reverse_width_step(prev.width_mm, order.width_mm)
        in_zone = transition_rules.in_reverse_zone(self._progress.cumulative_length_mm, self._constraints)
        reverse_count = self._progress.reverse_width_events_count + (1 if (is_reverse and in_zone) else 0)
        self._progress = CourseProgress(
            order_count=self._progress.order_count + 1,
            max_orders=self._progress.max_orders,
            cumulative_length_mm=self._progress.cumulative_length_mm + length,
            reverse_width_events_count=reverse_count,
            last_attributes=order.attributes,
        )

    def _episode_summary(self) -> dict:
        return {
            "course_order_counts": dict(self._course_order_counts),
            "main_orders_used": self._main_orders_used,
            "main_orders_total": self._main_orders_total,
            "coverage_ratio": rewards.manager_coverage_ratio(self._main_orders_used, self._main_orders_total),
        }
