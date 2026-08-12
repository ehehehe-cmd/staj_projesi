import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatSliderModule } from '@angular/material/slider';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Observable } from 'rxjs';

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
  imports: [MatCardModule, MatButtonModule, MatIconModule, MatSliderModule, KpiCardComponent, StatusBadgeComponent],
  template: `
    <h1>Dashboard</h1>

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

  readonly tickMs = signal(1000);
  readonly busy = signal(false);

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
