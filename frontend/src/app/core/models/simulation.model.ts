// backend/app/api/schemas.py ile birebir eşleşir (TASARIM.md §4, §7, §12.7).

export type SimulationMode = 'autonomous' | 'manual' | 'hybrid';
export type SimulationStatus = 'running' | 'paused' | 'stopped';

export interface SimulationRun {
  id: number;
  mode: SimulationMode;
  status: SimulationStatus;
  tick_interval_ms: number | null;
  manager_model_version_id: number | null;
  worker_model_version_id: number | null;
  config: Record<string, unknown> | null;
  started_at: string | null;
  stopped_at: string | null;
}

export interface SimulationStartRequest {
  mode?: SimulationMode;
  tick_interval_ms?: number | null;
  config?: Record<string, unknown> | null;
}

// backend/app/db/models.py::LiveEvent.event_type CHECK constraint (TASARIM.md §3.7)
// ile birebir — WS /ws/live üzerinden gelen payload'ların şekli.
export type LiveEventType =
  | 'order_generated'
  | 'course_started'
  | 'main_group_selected'
  | 'transition_selected'
  | 'slab_placed'
  | 'course_completed'
  | 'course_failed'
  | 'constraint_violation'
  | 'simulation_started'
  | 'simulation_paused'
  | 'simulation_resumed'
  | 'simulation_stopped'
  | 'manual_step';

export interface LiveEvent {
  id: number;
  event_type: LiveEventType;
  course_id: number | null;
  payload: Record<string, unknown>;
  created_at: string;
}
