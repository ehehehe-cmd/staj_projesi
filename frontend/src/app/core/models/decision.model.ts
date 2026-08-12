// backend/app/api/schemas.py ile birebir eşleşir (TASARIM.md §4, §12.7).

export interface ManagerDecision {
  kind: 'manager';
  id: number;
  course_id: number;
  step_index: number;
  selected_group_id: number | null;
  reward: number | null;
  model_version_id: number | null;
  decided_at: string;
}

export interface WorkerDecision {
  kind: 'worker';
  id: number;
  manager_decision_id: number;
  course_id: number;
  step_index: number;
  selected_transition_order_id: number | null;
  success: boolean | null;
  reward: number | null;
  model_version_id: number | null;
  decided_at: string;
}

export type Decision = ManagerDecision | WorkerDecision;

export interface DecisionsPage {
  items: Decision[];
  next_since: string | null;
}
