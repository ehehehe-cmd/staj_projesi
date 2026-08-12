import { Routes } from '@angular/router';

// TASARIM.md §9 — her feature sayfası lazy-loaded standalone bir
// component'tir; ilk yükleme bundle'ı tüm sayfaları DEĞİL, sadece
// aktif rotayı içerir.
export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  {
    path: 'dashboard',
    loadComponent: () => import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
    title: 'Dashboard',
  },
  {
    path: 'live-course',
    loadComponent: () => import('./features/live-course/live-course.component').then((m) => m.LiveCourseComponent),
    title: 'Aktif Kurs',
  },
  {
    path: 'order-pool',
    loadComponent: () => import('./features/order-pool/order-pool.component').then((m) => m.OrderPoolComponent),
    title: 'Order Havuzu',
  },
  {
    path: 'course-history',
    loadComponent: () =>
      import('./features/course-history/course-history.component').then((m) => m.CourseHistoryComponent),
    title: 'Kurs Geçmişi',
  },
  {
    path: 'decision-log',
    loadComponent: () => import('./features/decision-log/decision-log.component').then((m) => m.DecisionLogComponent),
    title: 'Karar Günlüğü',
  },
  {
    path: 'model-info',
    loadComponent: () => import('./features/model-info/model-info.component').then((m) => m.ModelInfoComponent),
    title: 'Model Bilgisi',
  },
  { path: '**', redirectTo: 'dashboard' },
];
