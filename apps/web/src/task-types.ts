export type TaskStatus = 'pending' | 'completed' | 'cancelled';
export interface Task {
  id: string; title: string; notes: string; status: TaskStatus; category: string; version: number;
  store_id: string | null; store_name: string | null; assignee_id: string; assignee_name: string;
  source_kind: string | null; source_id: string | null; source_number: string; action_kind: string;
  rule_id: string | null; due_date: string | null; due_time: string | null; timezone: string;
  follow_source: boolean; notify: boolean; source_changed_at: string | null; suppressed: boolean;
  completion_reason: string; history?: { id: string; action: string; data: Record<string, unknown>; created_at: string }[];
}
export interface TaskRule {
  id: string; title: string; kind: string; store_id: string | null; store_name: string | null;
  weekdays: number[]; due_time: string | null; timezone: string; offset_days: number;
  enabled: boolean; notify: boolean; version: number;
}
export interface TaskSource { kind: 'purchase' | 'shipment'; id: string; number: string; store_id: string }
