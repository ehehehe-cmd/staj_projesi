import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
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
 * havuzu, filtrelenebilir liste". Filtreleme İSTEMCİ TARAFINDA yapılır
 * (tüm grup/order'lar tek seferde çekilir, `status` bir `mat-select` ile
 * anlık olarak listeyi daraltır) — sunucudan durum başına ayrı sorgu atmak
 * bu ölçekte gereksiz bir round-trip olurdu.
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
    MatSelectModule,
    FormsModule,
    StatusBadgeComponent,
  ],
  template: `
    <h1>Order Havuzu</h1>

    <div class="toolbar">
      <button mat-raised-button color="primary" [disabled]="generating()" (click)="generate()">
        Yeni Sentetik Parti Üret
      </button>
    </div>

    <mat-card class="section-card" appearance="outlined">
      <div class="section-header">
        <h2>Ana Ürün Grupları ({{ filteredGroups().length }})</h2>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Durum</mat-label>
          <mat-select [(ngModel)]="groupStatusFilter">
            <mat-option value="all">Tümü</mat-option>
            <mat-option value="available">available</mat-option>
            <mat-option value="partially_used">partially_used</mat-option>
            <mat-option value="scheduled">scheduled</mat-option>
          </mat-select>
        </mat-form-field>
      </div>
      <table mat-table [dataSource]="filteredGroups()" class="data-table">
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
      @if (filteredGroups().length === 0) {
        <p class="empty">Bu filtreyle eşleşen ana ürün grubu yok.</p>
      }
    </mat-card>

    <mat-card class="section-card" appearance="outlined">
      <div class="section-header">
        <h2>Geçiş Order Havuzu ({{ filteredTransitions().length }})</h2>
        <mat-form-field appearance="outline" subscriptSizing="dynamic">
          <mat-label>Durum</mat-label>
          <mat-select [(ngModel)]="transitionStatusFilter">
            <mat-option value="all">Tümü</mat-option>
            <mat-option value="pending">pending</mat-option>
            <mat-option value="scheduled">scheduled</mat-option>
            <mat-option value="completed">completed</mat-option>
          </mat-select>
        </mat-form-field>
      </div>
      <table mat-table [dataSource]="filteredTransitions()" class="data-table">
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
      @if (filteredTransitions().length === 0) {
        <p class="empty">Bu filtreyle eşleşen geçiş order'ı yok.</p>
      }
    </mat-card>
  `,
  styles: `
    .toolbar {
      margin-bottom: 16px;
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

  private readonly allGroups = signal<MainGroup[]>([]);
  private readonly allTransitions = signal<SlabOrder[]>([]);
  readonly generating = signal(false);

  groupStatusFilter: 'all' | 'available' | 'partially_used' | 'scheduled' = 'all';
  transitionStatusFilter: 'all' | 'pending' | 'scheduled' | 'completed' = 'pending';

  readonly filteredGroups = computed(() => {
    const filter = this.groupStatusFilter;
    const groups = this.allGroups();
    return filter === 'all' ? groups : groups.filter((g) => g.status === filter);
  });

  readonly filteredTransitions = computed(() => {
    const filter = this.transitionStatusFilter;
    const orders = this.allTransitions();
    return filter === 'all' ? orders : orders.filter((o) => o.status === filter);
  });

  readonly groupColumns = ['id', 'steel_grade', 'group_size', 'status'];
  readonly orderColumns = ['id', 'steel_grade', 'width_mm', 'thickness_mm', 'status'];

  constructor() {
    this.load();
    effect(() => {
      const event = this.state.lastEvent();
      if (event && REFRESH_ON.has(event.event_type)) {
        this.load();
      }
    });
  }

  generate(): void {
    this.generating.set(true);
    this.api.generateOrders({ batches: 1 }).subscribe({
      next: (result) => {
        this.generating.set(false);
        this.snackBar.open(`${result.inserted_orders} order eklendi (${result.inserted_groups} grup)`, 'Kapat', {
          duration: 3000,
        });
        this.load();
      },
      error: () => {
        this.generating.set(false);
        this.snackBar.open('Order üretimi başarısız oldu', 'Kapat', { duration: 4000 });
      },
    });
  }

  private load(): void {
    this.api.listGroups({ limit: 300 }).subscribe((groups) => this.allGroups.set(groups));
    this.api.listOrders({ order_class: 'transition', limit: 300 }).subscribe((orders) => this.allTransitions.set(orders));
  }
}
