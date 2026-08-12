import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';

import { Course } from '../../core/models/course.model';
import { ApiService } from '../../core/services/api.service';
import { SimulationStateService } from '../../core/services/simulation-state.service';
import { StatusBadgeComponent } from '../../shared/components/status-badge/status-badge.component';

interface CourseRow extends Course {
  completionRate: number | null;
  durationSeconds: number | null;
}

const REFRESH_ON: ReadonlySet<string> = new Set(['course_completed', 'course_failed', 'course_started']);

/** TASARIM.md §9 "course-history" — "tamamlanmış kurslar tablosu
 * (completion oranı, süre, order sayısı)". */
@Component({
  selector: 'app-course-history',
  standalone: true,
  imports: [MatCardModule, MatTableModule, StatusBadgeComponent, DecimalPipe],
  template: `
    <h1>Kurs Geçmişi</h1>

    <mat-card class="section-card" appearance="outlined">
      <table mat-table [dataSource]="rows()" class="data-table">
        <ng-container matColumnDef="course_number">
          <th mat-header-cell *matHeaderCellDef>#</th>
          <td mat-cell *matCellDef="let c">{{ c.course_number }}</td>
        </ng-container>
        <ng-container matColumnDef="status">
          <th mat-header-cell *matHeaderCellDef>Durum</th>
          <td mat-cell *matCellDef="let c"><app-status-badge [status]="c.status" /></td>
        </ng-container>
        <ng-container matColumnDef="order_count">
          <th mat-header-cell *matHeaderCellDef>Order sayısı</th>
          <td mat-cell *matCellDef="let c">{{ c.order_count }} / {{ c.max_orders }}</td>
        </ng-container>
        <ng-container matColumnDef="completionRate">
          <th mat-header-cell *matHeaderCellDef>Doluluk oranı</th>
          <td mat-cell *matCellDef="let c">{{ c.completionRate !== null ? (c.completionRate * 100 | number: '1.0-1') + '%' : '—' }}</td>
        </ng-container>
        <ng-container matColumnDef="durationSeconds">
          <th mat-header-cell *matHeaderCellDef>Süre</th>
          <td mat-cell *matCellDef="let c">{{ c.durationSeconds !== null ? (c.durationSeconds | number: '1.0-1') + ' sn' : '—' }}</td>
        </ng-container>
        <ng-container matColumnDef="reverse_width_events_count">
          <th mat-header-cell *matHeaderCellDef>Ters-genişlik</th>
          <td mat-cell *matCellDef="let c">{{ c.reverse_width_events_count }}</td>
        </ng-container>

        <tr mat-header-row *matHeaderRowDef="columns"></tr>
        <tr mat-row *matRowDef="let row; columns: columns"></tr>
      </table>
      @if (rows().length === 0) {
        <p class="empty">Henüz kurs kaydı yok.</p>
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
export class CourseHistoryComponent {
  private readonly api = inject(ApiService);
  private readonly state = inject(SimulationStateService);

  private readonly courses = signal<Course[]>([]);

  readonly rows = computed<CourseRow[]>(() =>
    this.courses().map((course) => ({
      ...course,
      completionRate: course.max_orders ? course.order_count / course.max_orders : null,
      durationSeconds:
        course.started_at && course.completed_at
          ? (new Date(course.completed_at).getTime() - new Date(course.started_at).getTime()) / 1000
          : null,
    })),
  );

  readonly columns = [
    'course_number',
    'status',
    'order_count',
    'completionRate',
    'durationSeconds',
    'reverse_width_events_count',
  ];

  constructor() {
    this.load();
    effect(() => {
      const event = this.state.lastEvent();
      if (event && REFRESH_ON.has(event.event_type)) {
        this.load();
      }
    });
  }

  private load(): void {
    this.api.listCourses({ limit: 100 }).subscribe((courses) => this.courses.set(courses));
  }
}
