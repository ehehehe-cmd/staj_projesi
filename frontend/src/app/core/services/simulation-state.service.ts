import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { ActiveCourse, ActiveCourseSlot } from '../models/course.model';
import { ActiveModels } from '../models/model-version.model';
import { LiveEvent, SimulationRun } from '../models/simulation.model';
import { ApiService } from './api.service';
import { WsService } from './ws.service';

/** Birden fazla kursun slotlarını TEK, kesintisiz bir zaman çizelgesinde
 * (timeline) göstermek için `ActiveCourseSlot`'a eklenen alanlar — bkz.
 * `SimulationStateService.timelineSlots`. `global_position` kurslar arası
 * sürekli bir x-ekseni sağlar (her kursun kendi `position_index`'i 0'dan
 * başladığı için tek başına kullanılamaz). */
export interface TimelineSlot extends ActiveCourseSlot {
  course_id: number;
  course_number: number;
  course_status: string;
  global_position: number;
  is_course_start: boolean;
  is_course_end: boolean;
}

/** Angular signals ile güncel snapshot + event akışı — TASARIM.md §9.
 *
 * TASARIM.md İlke 4 ("Event sourcing + snapshot")'ün frontend tarafı:
 * uygulama açılışında REST ile bir snapshot alınır, ardından WS
 * olaylarıyla güncel TUTULUR. Bu servis KASITLI OLARAK "delta patch"
 * uygulamaz (ör. bir `main_group_selected` olayının payload'ından yeni
 * slot'u elle inşa etmek) — her ilgili olay geldiğinde etkilenen
 * kaynağı (`/api/courses/active`, `/api/simulation/status`) YENİDEN
 * ÇEKER. Gerekçe: bu ölçekte (küçük veri hacmi, tek operatör) bu, "her
 * olay tipi için elle state-patch mantığı yaz" yaklaşımından çok daha
 * az hataya açıktır ve backend'in TEK doğruluk kaynağı olma özelliğini
 * korur (İlke 1'in frontend'e yansıması) — bkz. TASARIM.md §12.8 karar
 * notu.
 */
@Injectable({ providedIn: 'root' })
export class SimulationStateService {
  private readonly api = inject(ApiService);
  private readonly ws = inject(WsService);

  readonly connected = this.ws.connected;

  /** "Aktif Kurs" grafiğinin kurs bittiğinde sıfırlanmaması, ardışık
   * kursları kesintisiz bir akış olarak göstermesi için tutulan geçmiş —
   * biten (completed/failed) kurslar burada, henüz devam eden kurs
   * `_activeCourse`'da. Bellek/grafik büyümesini sınırlamak için son
   * `MAX_HISTORY_COURSES` kursla sınırlıdır (eski uçtan atılır). */
  private static readonly MAX_HISTORY_COURSES = 20;

  private readonly _activeCourse = signal<ActiveCourse | null>(null);
  readonly activeCourse = this._activeCourse.asReadonly();

  private readonly _courseHistory = signal<ActiveCourse[]>([]);
  readonly courseHistory = this._courseHistory.asReadonly();

  /** Geçmiş (biten) kurslar + o an aktif kurs, tek bir sürekli slot
   * dizisine dönüştürülmüş hali — width-profile grafiğinin kaynağı.
   * `global_position` kurs sınırlarını aşan artan bir x-koordinatı verir;
   * `is_course_start`/`is_course_end` sınır işaretleyicileri (yeşil/mor
   * noktalar) için kullanılır. */
  readonly timelineSlots = computed<TimelineSlot[]>(() => {
    const active = this._activeCourse();
    const courses = active ? [...this._courseHistory(), active] : this._courseHistory();
    const result: TimelineSlot[] = [];
    let offset = 0;
    for (const course of courses) {
      const slots = course.slots.filter((s) => s.position_index !== null);
      slots.forEach((slot, i) => {
        result.push({
          ...slot,
          course_id: course.course_id,
          course_number: course.course_number,
          course_status: course.status,
          global_position: offset + i,
          is_course_start: i === 0,
          is_course_end: i === slots.length - 1 && course.status !== 'active',
        });
      });
      offset += slots.length;
    }
    return result;
  });

  private readonly _simulationRun = signal<SimulationRun | null>(null);
  readonly simulationRun = this._simulationRun.asReadonly();

  private readonly _activeModels = signal<ActiveModels | null>(null);
  readonly activeModels = this._activeModels.asReadonly();

  private readonly _lastEvent = signal<LiveEvent | null>(null);
  /** Diğer feature component'lerinin (order-pool, course-history,
   * decision-log) "ne zaman yeniden çekmeliyim" kararını vermek için
   * dinleyebileceği en son WS olayı. */
  readonly lastEvent = this._lastEvent.asReadonly();

  private started = false;

  constructor() {
    // WS her (yeniden) bağlandığında (İLK bağlantı DAHİL) snapshot'ı
    // tazele — İlke 4. effect() enjeksiyon bağlamı gerektirir (bu yüzden
    // BİR METOTTA değil, constructor'da oluşturulur); connect() henüz
    // çağrılmamış olsa bile güvenlidir (signal yalnızca connect() sonrası
    // true'ya döner, o ana kadar effect hiçbir şey yapmaz).
    effect(() => {
      if (this.ws.connected()) {
        this.refreshSnapshot();
      }
    });

    this.ws.events$.subscribe((event) => this.handleEvent(event));
  }

  /** Uygulama açılışında (app.component) BİR KEZ çağrılır. */
  start(): void {
    if (this.started) {
      return;
    }
    this.started = true;
    this.ws.connect();
  }

  refreshSnapshot(): void {
    this.api.getActiveCourse().subscribe((course) => this._activeCourse.set(course));
    this.api.getSimulationStatus().subscribe((run) => this._simulationRun.set(run));
    this.api.getActiveModels().subscribe((models) => this._activeModels.set(models));
  }

  /** Biten kursu, kapanış olayı gelir gelmez (henüz `_activeCourse`
   * `/api/courses/active`'ten yeniden çekilmeden ÖNCE, o sorgu artık bu
   * kursu döndürmeyecektir — view `status='active'`'e göre filtreliyor)
   * `_courseHistory`'ye taşır. Elimizdeki `_activeCourse` zaten bu kursun
   * tüm slotlarını içeriyor (önceki `main_group_selected`/
   * `transition_selected` olaylarıyla güncel tutuldu) — bu yüzden EK bir
   * API çağrısı gerekmez, sadece son bilinen anlık görüntü status'u
   * düzeltilip (olay geldiğinde henüz 'active' idi) arşive taşınır. */
  private archiveFinishedCourse(courseId: number | null, finalStatus: 'completed' | 'failed'): void {
    const finished = this._activeCourse();
    if (finished === null || finished.course_id !== courseId) {
      return;
    }
    this._courseHistory.update((history) => {
      const next = [...history, { ...finished, status: finalStatus }];
      return next.length > SimulationStateService.MAX_HISTORY_COURSES
        ? next.slice(next.length - SimulationStateService.MAX_HISTORY_COURSES)
        : next;
    });
  }

  private handleEvent(event: LiveEvent): void {
    this._lastEvent.set(event);

    if (event.event_type === 'course_completed' || event.event_type === 'course_failed') {
      this.archiveFinishedCourse(event.course_id, event.event_type === 'course_completed' ? 'completed' : 'failed');
    }

    const courseAffecting: ReadonlySet<string> = new Set([
      'course_started',
      'main_group_selected',
      'transition_selected',
      'slab_placed',
      'course_completed',
      'course_failed',
    ]);
    const runAffecting: ReadonlySet<string> = new Set([
      'simulation_started',
      'simulation_paused',
      'simulation_resumed',
      'simulation_stopped',
      'manual_step',
    ]);

    if (courseAffecting.has(event.event_type)) {
      this.api.getActiveCourse().subscribe((course) => this._activeCourse.set(course));
    }
    if (runAffecting.has(event.event_type)) {
      this.api.getSimulationStatus().subscribe((run) => this._simulationRun.set(run));
    }
  }
}
