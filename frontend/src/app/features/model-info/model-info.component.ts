import { DatePipe, JsonPipe } from '@angular/common';
import { Component, inject } from '@angular/core';
import { MatCardModule } from '@angular/material/card';

import { SimulationStateService } from '../../core/services/simulation-state.service';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';

/** TASARIM.md §9 "model-info" — "aktif manager/worker model bilgisi (salt
 * okunur, karşılaştırma paneli YOK)". Kapsam BİLİNÇLİ OLARAK dar tutulur:
 * hiçbir aktifleştirme/karşılaştırma kontrolü YOK (§0.2, §6:
 * "scripts/activate_model.py ile elle"). */
@Component({
  selector: 'app-model-info',
  standalone: true,
  imports: [MatCardModule, StatusBadgeComponent, DatePipe, JsonPipe],
  template: `
    <h1>Aktif Model Bilgisi</h1>

    @if (activeModels(); as models) {
      <div class="model-grid">
        @for (level of levels; track level) {
          <mat-card class="model-card" appearance="outlined">
            <h2>{{ level === 'manager' ? 'Manager' : 'Worker' }}</h2>
            @if (level === 'manager' ? models.manager : models.worker; as model) {
              <dl>
                <dt>Ad</dt>
                <dd>{{ model.name }}</dd>
                <dt>Durum</dt>
                <dd><app-status-badge [status]="model.is_active ? 'completed' : 'stopped'" /></dd>
                <dt>Eğitim tarihi</dt>
                <dd>{{ model.trained_at | date: 'medium' }}</dd>
                <dt>Checkpoint</dt>
                <dd class="mono">{{ model.checkpoint_path }}</dd>
                <dt>Metrikler</dt>
                <dd><pre class="mono">{{ model.metrics | json }}</pre></dd>
                <dt>Hiperparametreler</dt>
                <dd><pre class="mono">{{ model.hyperparams | json }}</pre></dd>
              </dl>
            } @else {
              <p class="empty">Aktif {{ level }} modeli yok.</p>
            }
          </mat-card>
        }
      </div>
    } @else {
      <p class="empty">Yükleniyor…</p>
    }
  `,
  styles: `
    .model-grid {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }
    .model-card {
      padding: 16px 20px;
      flex: 1 1 380px;
      min-width: 320px;
    }
    dl {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4px 12px;
      margin: 0;
    }
    dt {
      color: var(--app-text-muted, #8592a3);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      align-self: start;
      padding-top: 2px;
    }
    dd {
      margin: 0;
    }
    .mono {
      font-family: 'Roboto Mono', ui-monospace, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .empty {
      color: var(--app-text-muted, #8592a3);
    }
  `,
})
export class ModelInfoComponent {
  private readonly state = inject(SimulationStateService);

  readonly activeModels = this.state.activeModels;
  readonly levels = ['manager', 'worker'] as const;
}
