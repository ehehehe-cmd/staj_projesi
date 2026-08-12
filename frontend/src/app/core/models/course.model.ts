// backend/app/api/schemas.py ile birebir eşleşir (TASARIM.md §4, §12.7).

export type CourseStatus = 'pending' | 'active' | 'completed' | 'failed';
export type SlotRole = 'main' | 'transition';

export interface Course {
  id: number;
  course_number: number;
  status: CourseStatus;
  min_orders: number | null;
  max_orders: number | null;
  first_main_group_placed: boolean;
  current_length_mm: number | null;
  reverse_width_events_count: number;
  order_count: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface CourseSlot {
  id: number;
  course_id: number;
  position_index: number;
  slab_order_id: number | null;
  role: SlotRole;
  width_mm: number | null;
  thickness_mm: number | null;
  hardness: number | null;
  heating_temp_c: number | null;
  cumulative_length_mm: number | null;
  is_reverse_width: boolean;
  created_at: string;
}

export interface CourseDetail extends Course {
  slots: CourseSlot[];
}

// v_active_course_state (TASARIM.md §3.12) satırının HTTP karşılığı.
export interface ActiveCourseSlot {
  position_index: number | null;
  role: SlotRole | null;
  width_mm: number | null;
  thickness_mm: number | null;
  hardness: number | null;
  heating_temp_c: number | null;
  is_reverse_width: boolean | null;
  slab_order_id: number | null;
}

export interface ActiveCourse {
  course_id: number;
  course_number: number;
  status: string;
  order_count: number;
  current_length_mm: number | null;
  reverse_width_events_count: number;
  slots: ActiveCourseSlot[];
}
