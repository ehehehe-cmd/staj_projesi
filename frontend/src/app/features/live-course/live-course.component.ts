import { Component, inject } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';

import { SimulationStateService } from '../../core/services/simulation-state.service';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';
import { WidthProfileChartComponent } from '../../shared/components/width-profile-chart/width-profile-chart.component';

/** TASARIM.md §9 "live-course" — "aktif kursun slot dizisi: width-profile
 * grafiği (Figure 1 tarzı çift yönlü trapez), main (mavi) / transition
 * (turuncu) renk kodlama, reverse-width-zone vurgusu, hover'da thickness/
 * hardness/temp detayı". Grafiğin altında AYNI veriyi (hover gerektirmeden,
 * erişilebilirlik/tablo görünümü olarak) bir tablo halinde de gösterir. */
@Component({
  selector: 'app-live-course',
  standalone: true,
  imports: [MatCardModule, MatTableModule, StatusBadgeComponent, WidthProfileChartComponent],
  template: `
    <h1>Aktif Kurs</h1>

    @if (activeCourse(); as course) {
      <mat-card class="header-card" appearance="outlined">
        <div class="header-row">
          <span class="course-number">Kurs #{{ course.course_number }}</span>
          <app-status-badge [status]="course.status" />
          <span class="meta">{{ course.order_count }} order · {{ course.reverse_width_events_count }} ters-genişlik olayı</span>
        </div>
      </mat-card>

      <mat-card class="chart-card" appearance="outlined">
        <app-width-profile-chart [slots]="course.slots" />
      </mat-card>

      <mat-card class="table-card" appearance="outlined">
        <table mat-table [dataSource]="course.slots" class="slot-table">
          <ng-container matColumnDef="position_index">
            <th mat-header-cell *matHeaderCellDef>#</th>
            <td mat-cell *matCellDef="let slot">{{ slot.position_index }}</td>
          </ng-container>
          <ng-container matColumnDef="role">
            <th mat-header-cell *matHeaderCellDef>Rol</th>
            <td mat-cell *matCellDef="let slot">{{ slot.role }}</td>
          </ng-container>
          <ng-container matColumnDef="width_mm">
            <th mat-header-cell *matHeaderCellDef>Genişlik (mm)</th>
            <td mat-cell *matCellDef="let slot">{{ slot.width_mm }}</td>
          </ng-container>
          <ng-container matColumnDef="thickness_mm">
            <th mat-header-cell *matHeaderCellDef>Kalınlık (mm)</th>
            <td mat-cell *matCellDef="let slot">{{ slot.thickness_mm }}</td>
          </ng-container>
          <ng-container matColumnDef="hardness">
            <th mat-header-cell *matHeaderCellDef>Sertlik</th>
            <td mat-cell *matCellDef="let slot">{{ slot.hardness }}</td>
          </ng-container>
          <ng-container matColumnDef="heating_temp_c">
            <th mat-header-cell *matHeaderCellDef>Isıtma (°C)</th>
            <td mat-cell *matCellDef="let slot">{{ slot.heating_temp_c }}</td>
          </ng-container>
          <ng-container matColumnDef="is_reverse_width">
            <th mat-header-cell *matHeaderCellDef>Ters-genişlik</th>
            <td mat-cell *matCellDef="let slot">{{ slot.is_reverse_width ? 'evet' : '—' }}</td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="columns"></tr>
          <tr mat-row *matRowDef="let row; columns: columns"></tr>
        </table>
      </mat-card>
    } @else {
      <mat-card appearance="outlined" class="empty-card">
        <p>Şu anda aktif bir kurs yok.</p>
      </mat-card>
    }
  `,
  styles: `
    .header-card,
    .chart-card,
    .table-card,
    .empty-card {
      margin-bottom: 16px;
      padding: 16px 20px;
    }
    .header-row {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .course-number {
      font-weight: 600;
      font-size: 18px;
    }
    .meta {
      color: var(--app-text-muted, #8592a3);
      font-size: 13px;
    }
    .slot-table {
      width: 100%;
    }
  `,
})
export class LiveCourseComponent {
  private readonly state = inject(SimulationStateService);

  readonly activeCourse = this.state.activeCourse;
  readonly columns = [
    'position_index',
    'role',
    'width_mm',
    'thickness_mm',
    'hardness',
    'heating_temp_c',
    'is_reverse_width',
  ];
}
