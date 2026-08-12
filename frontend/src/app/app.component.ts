import { Component, inject } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { SimulationStateService } from './core/services/simulation-state.service';

interface NavLink {
  path: string;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatToolbarModule, MatSidenavModule, MatListModule, MatIconModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  // TASARIM.md §9 — snapshot+WS akışı uygulama açılışında BİR KEZ başlatılır
  // (bkz. simulation-state.service.ts); tüm feature sayfaları aynı örneği
  // paylaşır (providedIn: 'root').
  private readonly state = inject(SimulationStateService);

  readonly connected = this.state.connected;

  title = 'Sıcak Haddeleme HRL Çizelgeleme Sistemi';

  readonly navLinks: NavLink[] = [
    { path: '/dashboard', label: 'Dashboard', icon: 'dashboard' },
    { path: '/live-course', label: 'Aktif Kurs', icon: 'timeline' },
    { path: '/order-pool', label: 'Order Havuzu', icon: 'inventory_2' },
    { path: '/course-history', label: 'Kurs Geçmişi', icon: 'history' },
    { path: '/decision-log', label: 'Karar Günlüğü', icon: 'fact_check' },
    { path: '/model-info', label: 'Model Bilgisi', icon: 'model_training' },
  ];

  constructor() {
    this.state.start();
  }
}
