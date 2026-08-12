import { DatePipe } from '@angular/common';
import { Component, effect, inject, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';

import { Decision } from '../../core/models/decision.model';
import { ApiService } from '../../core/services/api.service';
import { SimulationStateService } from '../../core/services/simulation-state.service';

const DECISION_EVENT_TYPES: ReadonlySet<string> = new Set(['main_group_selected', 'transition_selected']);
const MAX_ROWS = 200;

/** TASARIM.md §9 "decision-log" — "manager/worker kararlarının canlı akan
 * feed'i". TASARIM.md §8'in reconnect/gap-fill sözleşmesini BİREBİR
 * uygular: "bağlantı koptuğunda kaçırılan olaylar created_at zaman
 * damgasına göre REST ile tamamlanır" — bu sayfa en son gördüğü
 * `decided_at`'i tutar, WS her (yeniden) bağlandığında
 * `GET /api/decisions?since=` ile kaçırdıklarını tamamlar (bkz.
 * backend/app/api/routers/decisions.py'nin aynı gerekçeli yorumu). */
@Component({
  selector: 'app-decision-log',
  standalone: true,
  imports: [MatCardModule, MatTableModule, DatePipe],
  template: `
    <h1>Karar Günlüğü</h1>

    <mat-card class="section-card" appearance="outlined">
      <table mat-table [dataSource]="decisions()" class="data-table">
        <ng-container matColumnDef="decided_at">
          <th mat-header-cell *matHeaderCellDef>Zaman</th>
          <td mat-cell *matCellDef="let d">{{ d.decided_at | date: 'HH:mm:ss.SSS' }}</td>
        </ng-container>
        <ng-container matColumnDef="kind">
          <th mat-header-cell *matHeaderCellDef>Tip</th>
          <td mat-cell *matCellDef="let d">{{ d.kind }}</td>
        </ng-container>
        <ng-container matColumnDef="course_id">
          <th mat-header-cell *matHeaderCellDef>Kurs</th>
          <td mat-cell *matCellDef="let d">{{ d.course_id }}</td>
        </ng-container>
        <ng-container matColumnDef="selection">
          <th mat-header-cell *matHeaderCellDef>Seçim</th>
          <td mat-cell *matCellDef="let d">{{ describeSelection(d) }}</td>
        </ng-container>
        <ng-container matColumnDef="reward">
          <th mat-header-cell *matHeaderCellDef>Ödül</th>
          <td mat-cell *matCellDef="let d">{{ d.reward ?? '—' }}</td>
        </ng-container>

        <tr mat-header-row *matHeaderRowDef="columns"></tr>
        <tr mat-row *matRowDef="let row; columns: columns"></tr>
      </table>
      @if (decisions().length === 0) {
        <p class="empty">Henüz karar kaydı yok.</p>
      }
    </mat-card>
  `,
  styles: `
    .section-card {
      padding: 16px 20px;
    }
    .data-table {
      width: 100%;
    }
    .empty {
      color: var(--app-text-muted, #8592a3);
      padding: 12px 0;
    }
  `,
})
export class DecisionLogComponent {
  private readonly api = inject(ApiService);
  private readonly state = inject(SimulationStateService);

  readonly decisions = signal<Decision[]>([]);
  readonly columns = ['decided_at', 'kind', 'course_id', 'selection', 'reward'];

  private lastKnownDecidedAt: string | null = null;
  private wasConnected = false;

  describeSelection(d: Decision): string {
    if (d.kind === 'manager') {
      return d.selected_group_id !== null ? `grup #${d.selected_group_id}` : 'kursu kapat';
    }
    const outcome = d.success === true ? 'başarılı' : d.success === false ? 'başarısız' : 'devam ediyor';
    return `order #${d.selected_transition_order_id} — ${outcome}`;
  }

  constructor() {
    this.loadInitial();

    effect(() => {
      const event = this.state.lastEvent();
      if (event && DECISION_EVENT_TYPES.has(event.event_type)) {
        this.fetchSince();
      }
    });

    // Reconnect gap-fill: bağlantı false->true'ya döndüğünde (İLK bağlantı
    // DAHİL değil -- o zaten loadInitial ile karşılanıyor) kaçırılanları
    // tamamla.
    effect(() => {
      const connected = this.state.connected();
      if (connected && this.wasConnected === false && this.lastKnownDecidedAt !== null) {
        this.fetchSince();
      }
      this.wasConnected = connected;
    });
  }

  private loadInitial(): void {
    this.api.listDecisions({ limit: MAX_ROWS }).subscribe((page) => {
      this.decisions.set(page.items);
      this.lastKnownDecidedAt = page.next_since;
    });
  }

  private fetchSince(): void {
    const since = this.lastKnownDecidedAt ?? undefined;
    this.api.listDecisions({ since, limit: MAX_ROWS }).subscribe((page) => {
      if (page.items.length === 0) {
        return;
      }
      this.lastKnownDecidedAt = page.next_since;
      const merged = [...this.decisions(), ...page.items];
      this.decisions.set(merged.slice(-MAX_ROWS));
    });
  }
}
