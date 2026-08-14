import { Component, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';

import { MainGroup, SlabOrder } from '../../core/models/order.model';
import { ApiService } from '../../core/services/api.service';
import { SimulationStateService } from '../../core/services/simulation-state.service';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';

const REFRESH_ON: ReadonlySet<string> = new Set([
  'order_generated',
  'main_group_selected',
  'transition_selected',
  'course_completed',
  'course_failed',
]);

/** TASARIM.md §9 "order-pool" — "bekleyen ana gruplar + geçiş order
 * havuzu, filtrelenebilir liste". Filtreleme SUNUCU TARAFINDA yapılır
 * (`status` değiştiğinde `GET /api/orders(/groups)?status=...` ile YENİDEN
 * çekilir).
 *
 * DEĞİŞİKLİK (istemci-taraflı filtrelemeden buraya geçiş gerekçesi): eski
 * tasarım tüm grup/order'ları TEK seferde (limit=300, id ARTAN sırada)
 * çekip filtrelemeyi bir `computed()` ile istemcide yapıyordu — "bu
 * ölçekte gereksiz round-trip olur" varsayımıyla. Ancak havuz aylar
 * içinde (demo/test kullanımıyla) binlerce satıra ulaşınca bu varsayım
 * çöktü: id ARTAN + limit=300 kombinasyonu, en YENİ (genelde `available`,
 * yani asıl aranan) satırları sessizce dışarıda bırakıyordu — kullanıcı
 * "available" filtresini seçtiğinde havuzda gerçekten var olan satırlar
 * bile hiç görünmüyordu, çünkü onlar zaten hiç indirilmemişti. Sunucu
 * taraflı filtre + id AZALAN sıralama (bkz. orders.py) bunu kökten
 * çözer: limit her zaman "durum eşleşen en YENİ N satır" anlamına gelir.
 *
 * `SimulationStateService.lastEvent` sinyalini dinleyerek havuzu ETKİLEYEN
 * olaylarda kendini yeniler (bkz. simulation-state.service.ts'in
 * modül-üstü yorumu — merkezi servis SADECE aktif kurs/simülasyon
 * durumunu tutar, havuz listesi her sayfanın kendi sorumluluğundadır). */
@Component({
  selector: 'app-order-pool',
  standalone: true,
  imports: [
    MatCardModule,
    MatButtonModule,
    MatTableModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatSelectModule,
    FormsModule,
    StatusBadgeComponent,
  ],
  template: `
    <h1>Order Havuzu</h1>

    <mat-card class="generate-card" appearance="outlined">
      <div class="generate-row">
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="batches-field">
          <mat-label>Parti sayısı</mat-label>
          <input matInput type="number" min="1" max="20" [(ngModel)]="batchCount" name="batchCount" />
        </mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="seed-field">
          <mat-label>Seed (opsiyonel)</mat-label>
          <input matInput type="number" [(ngModel)]="seedValue" name="seedValue" placeholder="rastgele" />
        </mat-form-field>
        <mat-checkbox [(ngModel)]="clearBeforeGenerate" name="clearBeforeGenerate">
          Önce bekleyen havuzu temizle
        </mat-checkbox>
        <button mat-raised-button color="primary" [disabled]="generating()" (click)="generate()">
          {{ clearBeforeGenerate ? 'Temizle ve Üret' : 'Üret' }}
        </button>
      </div>
      <!-- "Önce temizle" SADECE main_product_groups + henüz kursa yerleşmemiş
           slab_orders'ı siler (backend crud.clear_pending_pool) —
           tamamlanmış kurslar/kararlar/simülasyon geçmişi ETKİLENMEZ. -->
      <p class="hint">"Önce temizle" yalnızca bekleyen (henüz kursa yerleşmemiş) order/grupları siler — geçmiş kurslar, kararlar ve modeller etkilenmez.</p>
    </mat-card>

    <mat-card class="section-card" appearance="outlined">
      <div class="section-header">
        <h2>Ana Ürün Grupları ({{ groups().length }})</h2>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Durum</mat-label>
          <mat-select [(ngModel)]="groupStatusFilter" (selectionChange)="loadGroups()">
            <mat-option value="all">Tümü</mat-option>
            <mat-option value="available">available</mat-option>
            <mat-option value="partially_used">partially_used</mat-option>
            <mat-option value="scheduled">scheduled</mat-option>
          </mat-select>
        </mat-form-field>
      </div>
      <table mat-table [dataSource]="groups()" class="data-table">
        <ng-container matColumnDef="id">
          <th mat-header-cell *matHeaderCellDef>ID</th>
          <td mat-cell *matCellDef="let g">{{ g.id }}</td>
        </ng-container>
        <ng-container matColumnDef="steel_grade">
          <th mat-header-cell *matHeaderCellDef>Çelik kalitesi</th>
          <td mat-cell *matCellDef="let g">{{ g.steel_grade }}</td>
        </ng-container>
        <ng-container matColumnDef="group_size">
          <th mat-header-cell *matHeaderCellDef>Kalan / Toplam</th>
          <td mat-cell *matCellDef="let g">{{ g.group_size }} / {{ g.initial_group_size }}</td>
        </ng-container>
        <ng-container matColumnDef="status">
          <th mat-header-cell *matHeaderCellDef>Durum</th>
          <td mat-cell *matCellDef="let g"><app-status-badge [status]="g.status" /></td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="groupColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: groupColumns"></tr>
      </table>
      @if (groups().length === 0) {
        <p class="empty">Bu filtreyle eşleşen ana ürün grubu yok.</p>
      } @else if (groups().length >= listLimit) {
        <p class="empty">En yeni {{ listLimit }} kayıt gösteriliyor (daha fazlası olabilir).</p>
      }
    </mat-card>

    <mat-card class="section-card" appearance="outlined">
      <div class="section-header">
        <h2>Geçiş Order Havuzu ({{ transitions().length }})</h2>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Durum</mat-label>
          <mat-select [(ngModel)]="transitionStatusFilter" (selectionChange)="loadTransitions()">
            <mat-option value="all">Tümü</mat-option>
            <mat-option value="pending">pending</mat-option>
            <mat-option value="reserved">reserved</mat-option>
            <mat-option value="scheduled">scheduled</mat-option>
            <mat-option value="in_progress">in_progress</mat-option>
            <mat-option value="completed">completed</mat-option>
            <mat-option value="skipped">skipped</mat-option>
          </mat-select>
        </mat-form-field>
      </div>
      <table mat-table [dataSource]="transitions()" class="data-table">
        <ng-container matColumnDef="id">
          <th mat-header-cell *matHeaderCellDef>ID</th>
          <td mat-cell *matCellDef="let o">{{ o.id }}</td>
        </ng-container>
        <ng-container matColumnDef="steel_grade">
          <th mat-header-cell *matHeaderCellDef>Çelik kalitesi</th>
          <td mat-cell *matCellDef="let o">{{ o.steel_grade }}</td>
        </ng-container>
        <ng-container matColumnDef="width_mm">
          <th mat-header-cell *matHeaderCellDef>Genişlik (mm)</th>
          <td mat-cell *matCellDef="let o">{{ o.width_mm }}</td>
        </ng-container>
        <ng-container matColumnDef="thickness_mm">
          <th mat-header-cell *matHeaderCellDef>Kalınlık (mm)</th>
          <td mat-cell *matCellDef="let o">{{ o.thickness_mm }}</td>
        </ng-container>
        <ng-container matColumnDef="status">
          <th mat-header-cell *matHeaderCellDef>Durum</th>
          <td mat-cell *matCellDef="let o"><app-status-badge [status]="o.status" /></td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="orderColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: orderColumns"></tr>
      </table>
      @if (transitions().length === 0) {
        <p class="empty">Bu filtreyle eşleşen geçiş order'ı yok.</p>
      } @else if (transitions().length >= listLimit) {
        <p class="empty">En yeni {{ listLimit }} kayıt gösteriliyor (daha fazlası olabilir).</p>
      }
    </mat-card>
  `,
  styles: `
    .generate-card {
      margin-bottom: 16px;
      padding: 16px 20px;
    }
    .generate-row {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .batches-field {
      width: 120px;
    }
    .seed-field {
      width: 160px;
    }
    .hint {
      margin: 8px 0 0;
      color: var(--app-text-muted, #8592a3);
      font-size: 12px;
    }
    .section-card {
      margin-bottom: 16px;
      padding: 16px 20px;
    }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .section-header mat-form-field {
      width: 200px;
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
export class OrderPoolComponent {
  private readonly api = inject(ApiService);
  private readonly state = inject(SimulationStateService);
  private readonly snackBar = inject(MatSnackBar);

  readonly groups = signal<MainGroup[]>([]);
  readonly transitions = signal<SlabOrder[]>([]);
  readonly generating = signal(false);
  readonly listLimit = 300;

  batchCount = 5;
  seedValue: number | null = null;
  clearBeforeGenerate = false;

  // "available" varsayılanı bilinçli: sayfayı açan biri neredeyse hep
  // "şu an ne kullanılabilir" sorusunu soruyor — binlerce geçmiş
  // "scheduled" kaydı arasında kaybolmasın diye (bkz. dosya-üstü not).
  groupStatusFilter: 'all' | 'available' | 'partially_used' | 'scheduled' = 'available';
  transitionStatusFilter: 'all' | 'pending' | 'reserved' | 'scheduled' | 'in_progress' | 'completed' | 'skipped' =
    'pending';

  readonly groupColumns = ['id', 'steel_grade', 'group_size', 'status'];
  readonly orderColumns = ['id', 'steel_grade', 'width_mm', 'thickness_mm', 'status'];

  constructor() {
    this.loadGroups();
    this.loadTransitions();
    effect(() => {
      const event = this.state.lastEvent();
      if (event && REFRESH_ON.has(event.event_type)) {
        this.loadGroups();
        this.loadTransitions();
      }
    });
  }

  generate(): void {
    const batches = Math.min(20, Math.max(1, Math.round(this.batchCount || 1)));
    this.generating.set(true);
    this.api
      .generateOrders({
        batches,
        seed: this.seedValue ?? undefined,
        clear_pending: this.clearBeforeGenerate,
      })
      .subscribe({
        next: (result) => {
          this.generating.set(false);
          const clearedPart =
            result.cleared_orders > 0 ? `${result.cleared_orders} order temizlendi, ` : '';
          this.snackBar.open(
            `${clearedPart}${result.inserted_orders} order eklendi (${result.inserted_groups} grup)`,
            'Kapat',
            { duration: 3500 },
          );
          this.loadGroups();
          this.loadTransitions();
        },
        error: () => {
          this.generating.set(false);
          this.snackBar.open('Order üretimi başarısız oldu', 'Kapat', { duration: 4000 });
        },
      });
  }

  loadGroups(): void {
    const status = this.groupStatusFilter === 'all' ? undefined : this.groupStatusFilter;
    this.api.listGroups({ status, limit: this.listLimit }).subscribe((groups) => this.groups.set(groups));
  }

  loadTransitions(): void {
    const status = this.transitionStatusFilter === 'all' ? undefined : this.transitionStatusFilter;
    this.api
      .listOrders({ order_class: 'transition', status, limit: this.listLimit })
      .subscribe((orders) => this.transitions.set(orders));
  }
}
