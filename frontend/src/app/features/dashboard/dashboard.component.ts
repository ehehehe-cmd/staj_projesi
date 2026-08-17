import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable } from 'rxjs';

import { OrderStreamStatus, ResetForDemoResponse } from '../../core/models/order.model';
import { ApiService } from '../../core/services/api.service';
import { SimulationStateService } from '../../core/services/simulation-state.service';
import { KpiCardComponent } from '../../shared/components/kpi-card/kpi-card.component';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';

/** TASARIM.md §9 "dashboard" — "KPI kartları + simülasyon kontrol paneli
 * (start/pause/resume/stop, tick hızı slider'ı, 'Tek Adım İlerlet' butonu
 * — sadece paused iken aktif)". Bu component hiçbir state'i KENDİSİ
 * TUTMAZ — tamamı `SimulationStateService`'ten (snapshot+WS) okunur;
 * yalnızca butonların "meşgul/hata" gösterimi yerel state'tir. */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatSliderModule,
    MatFormFieldModule,
    MatInputModule,
    FormsModule,
    KpiCardComponent,
    StatusBadgeComponent,
  ],
  template: `
    <h1>Dashboard</h1>

    <mat-card class="reset-card" appearance="outlined">
      <div class="reset-row">
        <div class="reset-text">
          <strong>Sunuma Hazırla</strong>
          <span class="meta">
            Simülasyonu ve otomatik order akışını durdurur, bekleyen havuzu temizleyip taze/orantılı bir havuzla
            ({{ RESET_BATCHES }} parti, ~{{ RESET_BATCHES * 130 }} order) yeniden doldurur.
          </span>
        </div>
        <button mat-raised-button color="primary" [disabled]="resetBusy()" (click)="resetForDemo()">
          <mat-icon>restart_alt</mat-icon> Sunuma Hazırla
        </button>
      </div>
      @if (lastReset(); as r) {
        <p class="reset-result">
          Hazır — temizlenen: {{ r.cleared_orders }} order/{{ r.cleared_groups }} grup, eklenen: {{ r.inserted_orders }}
          order/{{ r.inserted_groups }} grup. Havuz: {{ r.pool_status.remaining_main_slabs }} slab /
          {{ r.pool_status.remaining_transition_orders }} geçiş order.
        </p>
      }
    </mat-card>

    <section class="kpi-row">
      <app-kpi-card label="Simülasyon durumu" [value]="simulationRun()?.status ?? 'yok'" />
      <app-kpi-card
        label="Aktif kurs"
        [value]="activeCourse() ? '#' + activeCourse()!.course_number : 'yok'"
        [hint]="activeCourse() ? activeCourse()!.status : null"
      />
      <app-kpi-card
        label="Kurstaki order"
        [value]="activeCourse() ? activeCourse()!.order_count : '—'"
      />
      <app-kpi-card label="WS bağlantısı" [value]="connected() ? 'bağlı' : 'koptu'" />
    </section>

    <mat-card class="control-panel" appearance="outlined">
      <div class="pool-header">
        <h2>Havuz Durumu</h2>
        <app-status-badge [status]="poolTone()" />
      </div>
      @if (poolStatus(); as pool) {
        <div class="pool-row">
          <app-kpi-card label="Kalan ana grup slabı" [value]="pool.remaining_main_slabs" [hint]="pool.remaining_main_groups + ' grup'" />
          <app-kpi-card label="Kalan geçiş order'ı" [value]="pool.remaining_transition_orders" />
        </div>
        @if (poolTone() !== 'sağlıklı') {
          <p class="pool-warning">
            Havuz {{ poolTone() === 'tükendi' ? 'tükendi' : 'azalıyor' }} — aşağıdan otomatik order akışını başlatabilir
            ya da elle <code>POST /api/orders/generate</code> çağırabilirsiniz.
          </p>
        }
      }

      <div class="stream-row">
        <app-status-badge [status]="streamStatus()?.running ? 'açık' : 'kapalı'" />
        @if (streamStatus()?.running) {
          <span class="stream-interval">hedef: en az {{ streamStatus()!.target_main_slabs }} slab (havuz altına düşerse otomatik doldurulur)</span>
        } @else {
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="target-field">
            <mat-label>Hedef slab sayısı</mat-label>
            <input matInput type="number" min="1" [(ngModel)]="targetMainSlabs" name="targetMainSlabs" />
          </mat-form-field>
        }
        <button mat-stroked-button class="btn-neutral" [disabled]="streamBusy() || !!streamStatus()?.running" (click)="startStream()">
          <mat-icon>play_arrow</mat-icon> Otomatik Doldurmayı Başlat
        </button>
        <button mat-stroked-button class="btn-neutral" [disabled]="streamBusy() || !streamStatus()?.running" (click)="stopStream()">
          <mat-icon>stop</mat-icon> Durdur
        </button>
      </div>
    </mat-card>

    <mat-card class="control-panel" appearance="outlined">
      <h2>Simülasyon Kontrolü</h2>

      <div class="status-line">
        Durum:
        @if (simulationRun(); as run) {
          <app-status-badge [status]="run.status" />
          <span class="mode">({{ run.mode }})</span>
        } @else {
          <app-status-badge status="stopped" />
        }
      </div>

      <div class="tick-row">
        <label id="tick-label">Tick süresi: {{ tickMs() }} ms</label>
        <mat-slider min="100" max="5000" step="100" aria-labelledby="tick-label">
          <input matSliderThumb [value]="tickMs()" (valueChange)="tickMs.set($event)" [disabled]="!canStart()" />
        </mat-slider>
      </div>

      <div class="actions">
        <button mat-raised-button color="primary" [disabled]="!canStart() || busy()" (click)="start()">
          <mat-icon>play_arrow</mat-icon> Başlat
        </button>
        <button mat-raised-button color="primary" [disabled]="!canResume() || busy()" (click)="resume()">
          <mat-icon>play_circle</mat-icon> Devam Et
        </button>
        <button mat-stroked-button class="btn-neutral" [disabled]="!canPause() || busy()" (click)="pause()">
          <mat-icon>pause</mat-icon> Duraklat
        </button>
        <button mat-stroked-button class="btn-neutral" [disabled]="!canStep() || busy()" (click)="step()">
          <mat-icon>skip_next</mat-icon> Tek Adım İlerlet
        </button>
        <button mat-flat-button color="warn" [disabled]="!canStop() || busy()" (click)="stop()">
          <mat-icon>stop</mat-icon> Durdur
        </button>
      </div>

      @if (activeModels(); as models) {
        <p class="model-line">
          Aktif model — manager: {{ models.manager?.name ?? 'yok' }} · worker: {{ models.worker?.name ?? 'yok' }}
        </p>
      }
    </mat-card>
  `,
  styles: `
    .reset-card {
      padding: 16px 20px;
      margin-bottom: 20px;
    }
    .reset-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }
    .reset-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
      max-width: 560px;
    }
    .reset-text .meta {
      font-size: 12.5px;
      color: var(--app-text-muted, #8592a3);
    }
    .reset-result {
      margin: 12px 0 0;
      font-size: 12.5px;
      color: var(--app-text-secondary, #48566b);
    }
    .kpi-row {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }
    .control-panel {
      padding: 16px 20px;
      max-width: 640px;
    }
    .control-panel + .control-panel {
      margin-top: 16px;
    }
    .pool-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .pool-header h2 {
      margin: 0;
    }
    .pool-row {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .pool-warning {
      margin: 12px 0 0;
      font-size: 12.5px;
      color: var(--app-text-secondary, #48566b);
    }
    .pool-warning code {
      font-size: 11.5px;
      background: var(--app-surface-alt, #f5f7fa);
      padding: 1px 5px;
      border-radius: 4px;
    }
    .stream-row {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid var(--app-border, #e1e5eb);
    }
    .stream-interval {
      font-size: 12.5px;
      color: var(--app-text-muted, #8592a3);
    }
    .target-field {
      width: 160px;
    }
    .status-line {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
    }
    .mode {
      color: var(--app-text-muted, #8592a3);
      font-size: 13px;
    }
    .tick-row {
      display: flex;
      flex-direction: column;
      margin-bottom: 8px;
    }
    .tick-row mat-slider {
      width: 100%;
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 12px 0;
    }
    .btn-neutral {
      color: var(--app-primary-light, #2e3b52);
      border-color: var(--app-primary-light, #2e3b52) !important;
    }
    .btn-neutral:disabled {
      color: rgba(0, 0, 0, 0.26);
      border-color: rgba(0, 0, 0, 0.12) !important;
    }
    .model-line {
      font-size: 13px;
      color: var(--app-text-secondary, #48566b);
      margin-top: 8px;
    }
  `,
})
export class DashboardComponent {
  private readonly api = inject(ApiService);
  private readonly state = inject(SimulationStateService);
  private readonly snackBar = inject(MatSnackBar);

  readonly simulationRun = this.state.simulationRun;
  readonly activeCourse = this.state.activeCourse;
  readonly activeModels = this.state.activeModels;
  readonly connected = this.state.connected;
  readonly poolStatus = this.state.poolStatus;

  // Eşikler kesin bir bilim değil — bu proje boyunca gözlenen tipik havuz
  // büyüklüklerine (yüzlerce-binlerce order) göre kaba bir "erken uyarı"
  // sınırı (bkz. docs/SONUCLAR.md, 2026-08-16/17: bir oturumun havuzu
  // sessizce 0'a düşürdüğü bulgusu).
  private static readonly POOL_LOW_THRESHOLD = 50;
  readonly poolTone = computed<'sağlıklı' | 'azalıyor' | 'tükendi'>(() => {
    const pool = this.poolStatus();
    if (!pool) {
      return 'sağlıklı';
    }
    if (pool.remaining_main_slabs === 0 || pool.remaining_transition_orders === 0) {
      return 'tükendi';
    }
    if (pool.remaining_main_slabs < DashboardComponent.POOL_LOW_THRESHOLD || pool.remaining_transition_orders < DashboardComponent.POOL_LOW_THRESHOLD) {
      return 'azalıyor';
    }
    return 'sağlıklı';
  });

  readonly tickMs = signal(1000);
  readonly busy = signal(false);

  readonly streamStatus = signal<OrderStreamStatus | null>(null);
  readonly streamBusy = signal(false);
  targetMainSlabs = 200;

  // TASARIM.md §9.3'te ölçülüp doğrulanan oran (~3400 slab / ~300 geçiş
  // order için 25 parti) — worker'ın hem çağrıldığı hem başarılı köprüler
  // kurduğu gözlenen büyüklük.
  readonly RESET_BATCHES = 25;
  readonly resetBusy = signal(false);
  readonly lastReset = signal<ResetForDemoResponse | null>(null);

  readonly canStart = computed(() => {
    const status = this.simulationRun()?.status;
    return status === undefined || status === null || status === 'stopped';
  });
  readonly canPause = computed(() => this.simulationRun()?.status === 'running');
  readonly canResume = computed(() => this.simulationRun()?.status === 'paused');
  readonly canStep = computed(() => this.simulationRun()?.status === 'paused');
  readonly canStop = computed(() => {
    const status = this.simulationRun()?.status;
    return status === 'running' || status === 'paused';
  });

  start(): void {
    this.run(this.api.startSimulation({ mode: 'hybrid', tick_interval_ms: this.tickMs() }));
  }

  pause(): void {
    this.run(this.api.pauseSimulation());
  }

  resume(): void {
    this.run(this.api.resumeSimulation());
  }

  stop(): void {
    this.run(this.api.stopSimulation());
  }

  step(): void {
    this.run(this.api.stepSimulation());
  }

  constructor() {
    this.api.getOrderStreamStatus().subscribe((status) => this.streamStatus.set(status));
  }

  startStream(): void {
    const target = Math.max(1, Math.round(this.targetMainSlabs || 1));
    this.streamBusy.set(true);
    this.api.startOrderStream({ target_main_slabs: target }).subscribe({
      next: (status) => {
        this.streamBusy.set(false);
        this.streamStatus.set(status);
      },
      error: (err: unknown) => {
        this.streamBusy.set(false);
        const detail = err instanceof HttpErrorResponse ? (err.error?.detail ?? err.message) : 'Bilinmeyen hata';
        this.snackBar.open(detail, 'Kapat', { duration: 4000 });
      },
    });
  }

  stopStream(): void {
    this.streamBusy.set(true);
    this.api.stopOrderStream().subscribe({
      next: (status) => {
        this.streamBusy.set(false);
        this.streamStatus.set(status);
      },
      error: (err: unknown) => {
        this.streamBusy.set(false);
        const detail = err instanceof HttpErrorResponse ? (err.error?.detail ?? err.message) : 'Bilinmeyen hata';
        this.snackBar.open(detail, 'Kapat', { duration: 4000 });
      },
    });
  }

  resetForDemo(): void {
    if (!confirm('Simülasyon durdurulacak, otomatik akış kapatılacak ve bekleyen order havuzu temizlenip yeniden doldurulacak. Devam edilsin mi?')) {
      return;
    }
    this.resetBusy.set(true);
    this.api.resetForDemo({ batches: this.RESET_BATCHES }).subscribe({
      next: (result) => {
        this.resetBusy.set(false);
        this.lastReset.set(result);
        this.state.refreshSnapshot();
        this.state.refreshPoolStatus();
        this.api.getOrderStreamStatus().subscribe((status) => this.streamStatus.set(status));
        this.snackBar.open('Sistem sunuma hazır.', 'Kapat', { duration: 4000 });
      },
      error: (err: unknown) => {
        this.resetBusy.set(false);
        const detail = err instanceof HttpErrorResponse ? (err.error?.detail ?? err.message) : 'Bilinmeyen hata';
        this.snackBar.open(detail, 'Kapat', { duration: 4000 });
      },
    });
  }

  private run(action: Observable<unknown>): void {
    this.busy.set(true);
    action.subscribe({
      next: () => {
        this.busy.set(false);
        this.state.refreshSnapshot();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        const detail = err instanceof HttpErrorResponse ? (err.error?.detail ?? err.message) : 'Bilinmeyen hata';
        this.snackBar.open(detail, 'Kapat', { duration: 4000 });
      },
    });
  }
}
