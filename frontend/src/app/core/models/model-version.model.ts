// backend/app/api/schemas.py ile birebir eşleşir (TASARIM.md §4, §12.7).

export interface ModelVersion {
  id: number;
  level: 'manager' | 'worker';
  name: string | null;
  checkpoint_path: string | null;
  trained_at: string | null;
  hyperparams: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
}

export interface ActiveModels {
  manager: ModelVersion | null;
  worker: ModelVersion | null;
}
