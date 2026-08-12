// backend/app/api/schemas.py ile birebir eşleşir (TASARIM.md §4, §12.7).

export type OrderClass = 'main' | 'transition';
export type OrderStatus = 'pending' | 'reserved' | 'scheduled' | 'in_progress' | 'completed' | 'skipped';
export type GroupStatus = 'available' | 'scheduled' | 'partially_used';

export interface SlabOrder {
  id: number;
  external_ref: string | null;
  steel_grade: string | null;
  width_mm: number | null;
  thickness_mm: number | null;
  hardness: number | null;
  heating_temp_c: number | null;
  slab_width_mm: number | null;
  slab_thickness_mm: number | null;
  slab_length_mm: number | null;
  theoretical_rolling_length: number | null;
  order_class: OrderClass;
  main_group_id: number | null;
  status: OrderStatus;
  source: 'synthetic' | 'manual';
  created_at: string;
}

export interface MainGroup {
  id: number;
  steel_grade: string | null;
  first_order_id: number | null;
  last_order_id: number | null;
  group_size: number | null;
  initial_group_size: number | null;
  status: GroupStatus;
  created_at: string;
}

export interface GenerateOrdersRequest {
  seed?: number | null;
  batches?: number;
  clear_pending?: boolean;
}

export interface GenerateOrdersResponse {
  inserted_orders: number;
  inserted_groups: number;
  cleared_orders: number;
  cleared_groups: number;
}
