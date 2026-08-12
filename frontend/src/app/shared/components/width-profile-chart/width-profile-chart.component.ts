import { Component, computed, input } from '@angular/core';
import type { EChartsOption } from 'echarts';
import { NgxEchartsDirective } from 'ngx-echarts';

import { ActiveCourseSlot } from '../../../core/models/course.model';

// dataviz skill'in validate_palette.js ile doğrulanmış kategorik çift'i —
// main (Erdemir mavisi) / transition (Erdemir kurumsal kırmızısı #d30013).
// `node scripts/validate_palette.js "#2a78d6,#d30013" --mode light` → TÜM
// kontroller PASS (ΔE 28.2 protan/deutan, ΔE 35.4 normal-vision, kontrast
// >=3:1 — bkz. TASARIM.md §12.8'in orijinal doğrulamasıyla aynı yöntem).
const COLOR_MAIN = '#2a78d6';
const COLOR_TRANSITION = '#d30013';
const COLOR_LINE = '#c7cedb'; // bağlayıcı profil çizgisi -- kendisi bir "seri kimliği" DEĞİL
const COLOR_AXIS = '#aab4c6';
const COLOR_GRID = '#e1e5eb';
const SURFACE = '#ffffff';

interface ChartPoint {
  value: [number, number];
  extra: ActiveCourseSlot;
  symbol?: string;
  symbolSize?: number;
}

interface TooltipParam {
  data?: ChartPoint;
}

/** Figure 1 tarzı çift-yönlü trapez genişlik profili — TASARIM.md §9
 * "live-course": "width-profile grafiği, main (mavi) / transition (turuncu)
 * renk kodlama, reverse-width-zone vurgusu, hover'da thickness/hardness/
 * temp detayı".
 *
 * Tasarım kararı (bkz. TASARIM.md §12.8): tek bir "profil" çizgisi (nötr
 * gri, sadece pozisyon-genişlik yolunu gösterir) + ÜZERİNE bindirilmiş iki
 * ayrı scatter serisi (main/transition, kategorik renk) olarak kuruldu —
 * ECharts'ın TEK bir seri içinde segment-bazlı renklendirmesi güvenilir
 * değildir; iki ayrı scatter serisi hem doğru bir legend (2 seri = legend
 * ZORUNLU, dataviz skill) hem de role-bazlı doğru renklendirme sağlar.
 * Ters-genişlik (reverse-width) noktaları renk YERİNE farklı bir sembolle
 * (elmas) işaretlenir — "identity is never color-alone" kuralı.
 */
@Component({
  selector: 'app-width-profile-chart',
  standalone: true,
  imports: [NgxEchartsDirective],
  template: `
    @if (slots().length > 0) {
      <div echarts [options]="chartOptions()" class="chart"></div>
    } @else {
      <p class="empty">Aktif kursta henüz slot yok.</p>
    }
  `,
  styles: `
    .chart {
      height: 360px;
      width: 100%;
    }
    .empty {
      color: var(--app-text-muted, #8592a3);
      padding: 32px 0;
      text-align: center;
    }
  `,
})
export class WidthProfileChartComponent {
  readonly slots = input.required<ActiveCourseSlot[]>();

  readonly chartOptions = computed<EChartsOption>(() => this.buildOptions(this.slots()));

  private buildOptions(slots: ActiveCourseSlot[]): EChartsOption {
    const toPoint = (slot: ActiveCourseSlot): ChartPoint => ({
      value: [slot.position_index ?? 0, slot.width_mm ?? 0],
      extra: slot,
      ...(slot.is_reverse_width ? { symbol: 'diamond', symbolSize: 14 } : {}),
    });

    const mainPoints = slots.filter((s) => s.role === 'main').map(toPoint);
    const transitionPoints = slots.filter((s) => s.role === 'transition').map(toPoint);
    const linePoints = slots.map((s): [number, number] => [s.position_index ?? 0, s.width_mm ?? 0]);

    return {
      grid: { left: 56, right: 24, top: 48, bottom: 40 },
      legend: {
        top: 4,
        data: ['Ana ürün (main)', 'Geçiş (transition)'],
        textStyle: { color: '#48566b' },
      },
      xAxis: {
        type: 'value',
        name: 'Pozisyon (k)',
        nameLocation: 'middle',
        nameGap: 28,
        minInterval: 1,
        axisLine: { lineStyle: { color: COLOR_AXIS } },
        splitLine: { lineStyle: { color: COLOR_GRID } },
      },
      yAxis: {
        type: 'value',
        name: 'Genişlik (mm)',
        nameLocation: 'middle',
        nameGap: 44,
        axisLine: { lineStyle: { color: COLOR_AXIS } },
        splitLine: { lineStyle: { color: COLOR_GRID } },
      },
      tooltip: {
        trigger: 'item',
        // ECharts'ın formatter callback tipi (TopLevelFormatterParams) tüm
        // seri tiplerini (pie/sankey/graph/...) kapsayan çok geniş bir
        // union'dır; bizim TEK bilinen şeklimiz (ChartPoint) için elle
        // daraltmak yerine burada bilinçli olarak `unknown` + runtime
        // kontrolü kullanılır.
        formatter: (params: unknown) => {
          const single = (Array.isArray(params) ? params[0] : params) as TooltipParam | undefined;
          const slot = single?.data?.extra;
          if (!slot) {
            return '';
          }
          const lines = [
            `<strong>#${slot.position_index} — ${slot.role}</strong>`,
            `Genişlik: ${slot.width_mm} mm`,
            `Kalınlık: ${slot.thickness_mm} mm`,
            `Sertlik: ${slot.hardness}`,
            `Isıtma sıcaklığı: ${slot.heating_temp_c} °C`,
          ];
          if (slot.is_reverse_width) {
            lines.push('<em>ters-genişlik adımı</em>');
          }
          return lines.join('<br/>');
        },
      },
      series: [
        {
          name: 'Profil',
          type: 'line',
          data: linePoints,
          symbol: 'none',
          silent: true,
          lineStyle: { width: 2, color: COLOR_LINE },
          z: 1,
        },
        {
          name: 'Ana ürün (main)',
          type: 'scatter',
          data: mainPoints,
          symbolSize: 10,
          itemStyle: { color: COLOR_MAIN, borderColor: SURFACE, borderWidth: 2 },
          z: 2,
        },
        {
          name: 'Geçiş (transition)',
          type: 'scatter',
          data: transitionPoints,
          symbolSize: 10,
          itemStyle: { color: COLOR_TRANSITION, borderColor: SURFACE, borderWidth: 2 },
          z: 2,
        },
      ],
    };
  }
}
