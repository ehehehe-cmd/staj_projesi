import { Injectable, effect, inject, signal } from '@angular/core';

import { ActiveCourse } from '../models/course.model';
import { ActiveModels } from '../models/model-version.model';
import { LiveEvent, SimulationRun } from '../models/simulation.model';
import { ApiService } from './api.service';
import { WsService } from './ws.service';

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

  private readonly _activeCourse = signal<ActiveCourse | null>(null);
  readonly activeCourse = this._activeCourse.asReadonly();

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

  private handleEvent(event: LiveEvent): void {
    this._lastEvent.set(event);

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
