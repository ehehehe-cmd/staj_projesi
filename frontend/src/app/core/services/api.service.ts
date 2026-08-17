import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { ActiveCourse, Course, CourseDetail } from '../models/course.model';
import { DecisionsPage } from '../models/decision.model';
import { ActiveModels, ModelVersion } from '../models/model-version.model';
import {
  GenerateOrdersRequest,
  GenerateOrdersResponse,
  MainGroup,
  OrderStreamStartRequest,
  OrderStreamStatus,
  PoolStatus,
  ResetForDemoRequest,
  ResetForDemoResponse,
  SlabOrder,
} from '../models/order.model';
import { SimulationRun, SimulationStartRequest } from '../models/simulation.model';

/** HttpClient sarmalayıcısı — TASARIM.md §9. Backend'in (Faz 6) REST
 * sözleşmesini (app/api/routers/*.py, app/api/schemas.py) BİREBİR yansıtır;
 * hiçbir iş mantığı/dönüşüm YAPMAZ (o iş simulation-state.service.ts'e
 * ve feature component'lerine aittir). */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  // ── orders (TASARIM.md §4, §9 "order-pool") ──────────────────────

  listOrders(params: { status?: string; order_class?: string; main_group_id?: number; limit?: number } = {}): Observable<SlabOrder[]> {
    return this.http.get<SlabOrder[]>(`${this.base}/api/orders`, { params: this.toHttpParams(params) });
  }

  listGroups(params: { status?: string; limit?: number } = {}): Observable<MainGroup[]> {
    return this.http.get<MainGroup[]>(`${this.base}/api/orders/groups`, { params: this.toHttpParams(params) });
  }

  generateOrders(body: GenerateOrdersRequest): Observable<GenerateOrdersResponse> {
    return this.http.post<GenerateOrdersResponse>(`${this.base}/api/orders/generate`, body);
  }

  getPoolStatus(): Observable<PoolStatus> {
    return this.http.get<PoolStatus>(`${this.base}/api/orders/pool-status`);
  }

  getOrderStreamStatus(): Observable<OrderStreamStatus> {
    return this.http.get<OrderStreamStatus>(`${this.base}/api/orders/stream/status`);
  }

  startOrderStream(body: OrderStreamStartRequest): Observable<OrderStreamStatus> {
    return this.http.post<OrderStreamStatus>(`${this.base}/api/orders/stream/start`, body);
  }

  stopOrderStream(): Observable<OrderStreamStatus> {
    return this.http.post<OrderStreamStatus>(`${this.base}/api/orders/stream/stop`, {});
  }

  resetForDemo(body: ResetForDemoRequest = {}): Observable<ResetForDemoResponse> {
    return this.http.post<ResetForDemoResponse>(`${this.base}/api/orders/reset-for-demo`, body);
  }

  // ── courses (§9 "live-course" / "course-history") ────────────────

  listCourses(params: { status?: string; limit?: number } = {}): Observable<Course[]> {
    return this.http.get<Course[]>(`${this.base}/api/courses`, { params: this.toHttpParams(params) });
  }

  getActiveCourse(): Observable<ActiveCourse | null> {
    return this.http.get<ActiveCourse | null>(`${this.base}/api/courses/active`);
  }

  getCourse(id: number): Observable<CourseDetail> {
    return this.http.get<CourseDetail>(`${this.base}/api/courses/${id}`);
  }

  // ── decisions (§9 "decision-log") ─────────────────────────────────

  listDecisions(
    params: { kind?: 'manager' | 'worker'; course_id?: number; since?: string; limit?: number } = {},
  ): Observable<DecisionsPage> {
    return this.http.get<DecisionsPage>(`${this.base}/api/decisions`, { params: this.toHttpParams(params) });
  }

  // ── models (§9 "model-info") ───────────────────────────────────────

  listModels(params: { level?: 'manager' | 'worker'; is_active?: boolean; limit?: number } = {}): Observable<ModelVersion[]> {
    return this.http.get<ModelVersion[]>(`${this.base}/api/models`, { params: this.toHttpParams(params) });
  }

  getActiveModels(): Observable<ActiveModels> {
    return this.http.get<ActiveModels>(`${this.base}/api/models/active`);
  }

  // ── simulation control (§9 "dashboard") ─────────────────────────────

  getSimulationStatus(): Observable<SimulationRun | null> {
    return this.http.get<SimulationRun | null>(`${this.base}/api/simulation/status`);
  }

  startSimulation(body: SimulationStartRequest): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`${this.base}/api/simulation/start`, body);
  }

  pauseSimulation(): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`${this.base}/api/simulation/pause`, {});
  }

  resumeSimulation(): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`${this.base}/api/simulation/resume`, {});
  }

  stopSimulation(): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`${this.base}/api/simulation/stop`, {});
  }

  stepSimulation(): Observable<{ detail: string }> {
    return this.http.post<{ detail: string }>(`${this.base}/api/simulation/step`, {});
  }

  private toHttpParams(params: Record<string, string | number | boolean | undefined>): HttpParams {
    let httpParams = new HttpParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        httpParams = httpParams.set(key, String(value));
      }
    }
    return httpParams;
  }
}
