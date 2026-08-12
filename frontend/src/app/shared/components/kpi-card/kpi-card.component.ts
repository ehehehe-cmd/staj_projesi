import { Component, input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';

/** TASARIM.md §9 "shared/components/kpi-card" — dashboard'daki KPI
 * kartları için tek, tekrar kullanılabilir gösterim. Stat-tile sözleşmesi:
 * label (büyük harfle başlamayan kısa etiket) + value (büyük, orantılı
 * rakamlar) + isteğe bağlı hint. */
@Component({
  selector: 'app-kpi-card',
  standalone: true,
  imports: [MatCardModule],
  template: `
    <mat-card class="kpi-card" appearance="outlined">
      <div class="kpi-label">{{ label() }}</div>
      <div class="kpi-value">{{ value() }}</div>
      @if (hint()) {
        <div class="kpi-hint">{{ hint() }}</div>
      }
    </mat-card>
  `,
  styles: `
    .kpi-card {
      padding: 14px 18px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 150px;
      border-left: 3px solid var(--app-primary, #07254f) !important;
    }
    .kpi-label {
      font-size: 11px;
      font-weight: 700;
      color: var(--app-text-secondary, #48566b);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .kpi-value {
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: var(--app-text, #101826);
      line-height: 1.2;
      font-variant-numeric: proportional-nums;
    }
    .kpi-hint {
      font-size: 12px;
      color: var(--app-text-muted, #8592a3);
    }
  `,
})
export class KpiCardComponent {
  readonly label = input.required<string>();
  readonly value = input.required<string | number>();
  readonly hint = input<string | null>(null);
}
