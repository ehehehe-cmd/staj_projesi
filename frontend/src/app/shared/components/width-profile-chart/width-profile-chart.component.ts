import { Component, computed, input } from '@angular/core';
import type { EChartsOption } from 'echarts';
import { NgxEchartsDirective } from 'ngx-echarts';

import { TimelineSlot } from '../../../core/services/simulation-state.service';

// dataviz skill'in validate_palette.js ile doğrulanmış kategorik çift'i —
// main (Erdemir mavisi) / transition (Erdemir kurumsal kırmızısı #d30013).
// `node scripts/validate_palette.js "#2a78d6,#d30013" --mode light` → TÜM
// kontroller PASS (ΔE 28.2 protan/deutan, ΔE 35.4 normal-vision, kontrast
// >=3:1 — bkz. TASARIM.md §12.8'in orijinal doğrulamasıyla aynı yöntem).
const COLOR_MAIN = '#2a78d6';
const COLOR_TRANSITION = '#d30013';
// Kurs-sınırı işaretleyicileri (yeşil=başlangıç, mor=bitiş) — AYRI bir
// doğrulama turu gerekti: kırmızı (#d30013, yukarıdaki transition rengi)
// zaten kullanımda olduğu için "kurs bitişi" için de kırmızı denemek
// `validate_palette.js`'te sert FAIL verdi (ΔE 4.8, tam renk görüşünde bile
// ayırt edilemez — status "critical" #d03b3b bile transition kırmızısına
// çok yakın çıktı). Mor (#4a3aa7), mevcut mavi/kırmızı/yeşil ile
// `--pairs all` altında SIFIR çakışmayla geçti; kullanıcıyla bu doğrulanmış
// alternatif üzerinde anlaşıldı (kırmızı yerine).
const COLOR_COURSE_START = '#0ca30c'; // durum paleti "good" — hiçbir seriyle çakışmıyor
const COLOR_COURSE_END = '#4a3aa7'; // doğrulanmış mor — kırmızıyla ΔE çakışmasını önler
const COLOR_LINE = '#c7cedb'; // bağlayıcı profil çizgisi -- kendisi bir "seri kimliği" DEĞİL
const COLOR_AXIS = '#aab4c6';
const COLOR_GRID = '#e1e5eb';
const COLOR_BOUNDARY_LINE = '#c7cedb'; // kurs sınırı dikey çizgisi -- nötr, yeni bir "seri kimliği" değil
const SURFACE = '#ffffff';

interface ChartPoint {
  value: [number, number];
  extra: TimelineSlot;
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
 *
 * Kurslar arası süreklilik (bu değişiklik): önceden grafik SADECE aktif
 * kursu gösterip kurs bitince sıfırlanıyordu. Artık `slots` girdisi
 * `SimulationStateService.timelineSlots`'tan geliyor — biten kursların
 * slotları da `global_position` ile aynı x-eksenine dizilip birikiyor,
 * grafik kurs geçişlerinde sıfırlanmıyor. Her kursun İLK slotu yeşil
 * (`is_course_start`), TAMAMLANMIŞ/BAŞARISIZ her kursun SON slotu mor
 * (`is_course_end`) — main/transition renklerinden AYRI iki üçüncü/dördüncü
 * scatter serisi olarak, role-rengi ÜZERİNE bindirilmiş biçimde (aynı
 * noktada iki katman: rol rengi + sınır işaretleyicisi, farklı sembol
 * şekliyle ayırt edilir).
 *
 * Yoğunluk düzeltmesi (ikinci tur): çok sayıda kurs birikince (a) her kurs
 * sınırına DAİMİ bir metin etiketi ("Kurs N") basmak üst üste binip
 * okunmaz hale geliyordu — bu yüzden sınırlar artık SADECE ince kesikli
 * çizgi, kurs numarası tıklanan/üzerine gelinen noktanın tooltip'inde
 * kalıyor (aşağıdaki `tooltip.formatter`). (b) TÜM geçmiş tek ekranda
 * sıkışınca noktalar (özellikle nadir geçiş/transition noktaları) birbirine
 * karışıyordu — `dataZoom` ile varsayılan görünüm SON `windowSize`
 * pozisyona daraltıldı (veri kaybı YOK, geri kalan geçmiş slider'la
 * gezilebilir kalıyor).
 */
@Component({
  selector: 'app-width-profile-chart',
  standalone: true,
  imports: [NgxEchartsDirective],
  template: `
    @if (slots().length > 0) {
      <div echarts [options]="chartOptions()" class="chart"></div>
    } @else {
      <p class="empty">Henüz slot yok.</p>
    }
  `,
  styles: `
    .chart {
      height: 420px;
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
  readonly slots = input.required<TimelineSlot[]>();
  /** Varsayılan görünümde SONdan kaç pozisyonun gösterileceği — daha eski
   * geçmiş silinmiyor, sadece `dataZoom` slider'ıyla geri gezilebiliyor. */
  readonly windowSize = input(500);

  readonly chartOptions = computed<EChartsOption>(() => this.buildOptions(this.slots(), this.windowSize()));

  private buildOptions(slots: TimelineSlot[], windowSize: number): EChartsOption {
    const toPoint = (slot: TimelineSlot): ChartPoint => ({
      value: [slot.global_position, slot.width_mm ?? 0],
      extra: slot,
      ...(slot.is_reverse_width ? { symbol: 'diamond', symbolSize: 14 } : {}),
    });

    const mainPoints = slots.filter((s) => s.role === 'main').map(toPoint);
    const transitionPoints = slots.filter((s) => s.role === 'transition').map(toPoint);
    const startPoints = slots
      .filter((s) => s.is_course_start)
      .map((s): ChartPoint => ({ ...toPoint(s), symbol: 'triangle', symbolSize: 17 }));
    const endPoints = slots
      .filter((s) => s.is_course_end)
      .map((s): ChartPoint => ({ ...toPoint(s), symbol: 'rect', symbolSize: 14 }));
    const linePoints = slots.map((s): [number, number] => [s.global_position, s.width_mm ?? 0]);

    const boundaryMarkLines = slots
      .filter((s) => s.is_course_start)
      .map((s) => ({
        xAxis: s.global_position,
        label: { show: false },
        lineStyle: { color: COLOR_BOUNDARY_LINE, type: 'dashed' as const, width: 1 },
      }));

    const maxPosition = slots.length > 0 ? slots[slots.length - 1].global_position : 0;
    const windowStart = Math.max(0, maxPosition - windowSize);

    return {
      grid: { left: 56, right: 24, top: 48, bottom: 68 },
      legend: {
        top: 4,
        data: ['Ana ürün (main)', 'Geçiş (transition)', 'Kurs başlangıcı', 'Kurs bitişi'],
        textStyle: { color: '#48566b' },
      },
      xAxis: {
        type: 'value',
        name: 'Pozisyon (sürekli)',
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
      // Varsayılan görünüm son `windowSize` pozisyonla sınırlı (yoğunluk
      // şikayeti — bkz. dosya-üstü not); veri BUDANMIYOR, kullanıcı
      // slider'ı sola sürükleyerek tüm geçmişi gezebilir.
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, startValue: windowStart, endValue: maxPosition },
        {
          type: 'slider',
          xAxisIndex: 0,
          startValue: windowStart,
          endValue: maxPosition,
          height: 20,
          bottom: 8,
          borderColor: COLOR_GRID,
          fillerColor: 'rgba(42,120,214,0.08)',
          handleStyle: { color: COLOR_AXIS },
        },
      ],
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
            `<strong>Kurs ${slot.course_number} · #${slot.position_index} — ${slot.role}</strong>`,
            `Genişlik: ${slot.width_mm} mm`,
            `Kalınlık: ${slot.thickness_mm} mm`,
            `Sertlik: ${slot.hardness}`,
            `Isıtma sıcaklığı: ${slot.heating_temp_c} °C`,
          ];
          if (slot.is_reverse_width) {
            lines.push('<em>ters-genişlik adımı</em>');
          }
          if (slot.is_course_start) {
            lines.push('<em>kurs başlangıcı</em>');
          }
          if (slot.is_course_end) {
            lines.push(`<em>kurs bitişi (${slot.course_status})</em>`);
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
          markLine: {
            silent: true,
            symbol: 'none',
            data: boundaryMarkLines,
            z: 1,
          },
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
          // Nadir görülen geçiş order'ları ana üründen biraz daha büyük
          // çizilir (10→13) — havuz bol olduğunda çoğu geçiş worker'sız
          // atlandığı için (bkz. docs/RAPOR.md "tavan etkisi") ekranda az
          // sayıda görünüyor, boyut farkı onları kaybolmaktan korur.
          name: 'Geçiş (transition)',
          type: 'scatter',
          data: transitionPoints,
          symbolSize: 13,
          itemStyle: { color: COLOR_TRANSITION, borderColor: SURFACE, borderWidth: 2 },
          z: 2,
        },
        {
          // Kurs başlangıcı: role-rengi ÜZERİNE bindirilmiş, farklı sembol
          // (üçgen) + doğrulanmış yeşil — "identity is never color-alone"
          // (bkz. yukarıdaki dosya-üstü not).
          name: 'Kurs başlangıcı',
          type: 'scatter',
          data: startPoints,
          itemStyle: { color: COLOR_COURSE_START, borderColor: SURFACE, borderWidth: 2 },
          z: 3,
        },
        {
          // Kurs bitişi: kırmızı YERİNE doğrulanmış mor + farklı sembol
          // (kare) — mevcut "Geçiş (transition)" kırmızısıyla karışmasın
          // diye bilinçli olarak kırmızı DEĞİL (bkz. dosya-üstü not).
          name: 'Kurs bitişi',
          type: 'scatter',
          data: endPoints,
          itemStyle: { color: COLOR_COURSE_END, borderColor: SURFACE, borderWidth: 2 },
          z: 3,
        },
      ],
    };
  }
}
