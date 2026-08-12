import { Component, computed, input } from '@angular/core';

type StatusTone = 'good' | 'warning' | 'serious' | 'critical' | 'neutral';

// dataviz skill'in sabit "status palette"i (good/warning/serious/critical) —
// asla kategorik seri renkleriyle (width-profile-chart'ın mavi/turuncusu)
// karıştırılmaz, her zaman ikon+etiketle birlikte gösterilir (renk TEK
// BAŞINA anlam taşımaz).
const TONE_BY_STATUS: Record<string, StatusTone> = {
  // kurs / order-havuzu (main_product_groups, slab_orders)
  completed: 'good',
  available: 'good',
  running: 'good',
  active: 'serious',
  in_progress: 'serious',
  scheduled: 'serious',
  reserved: 'serious',
  pending: 'warning',
  paused: 'warning',
  partially_used: 'warning',
  failed: 'critical',
  skipped: 'critical',
  stopped: 'neutral',
};

const COLOR_BY_TONE: Record<StatusTone, string> = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
  neutral: '#898781',
};

/** TASARIM.md §9 "shared/components/status-badge" — kurs/simülasyon/order/
 * grup durumlarının HEPSİ için tek, tutarlı gösterim. Renk TEK BAŞINA anlam
 * taşımayacak şekilde her zaman bir nokta işareti + metin etiketiyle
 * birlikte gösterilir (dataviz skill'inin "status colors... never color
 * alone" kuralı). */
@Component({
  selector: 'app-status-badge',
  standalone: true,
  template: `
    <span class="status-badge">
      <span class="dot" [style.background]="color()"></span>
      {{ status() }}
    </span>
  `,
  styles: `
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12.5px;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 12px;
      background: var(--app-surface-alt, #f5f7fa);
      border: 1px solid var(--app-border, #e1e5eb);
      color: var(--app-text-secondary, #48566b);
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex: none;
    }
  `,
})
export class StatusBadgeComponent {
  readonly status = input.required<string>();
  readonly color = computed(() => COLOR_BY_TONE[TONE_BY_STATUS[this.status()] ?? 'neutral']);
}
