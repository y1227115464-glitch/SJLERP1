export type RoleKey = 'admin' | 'manager' | 'operator' | 'finance' | 'warehouse';
export interface User {
  id: string; email: string; display_name: string; role: RoleKey; is_active: boolean;
  store_ids: string[]; permissions: string[];
}
export interface Store {
  id: string; name: string; code: string; legal_entity: string; brand: string;
  marketplace: string; currency: string; is_active: boolean; created_at: string;
}
export interface Role { key: RoleKey; label: string; permissions: string[] }
export interface Audit {
  id: string; action: string; resource_type: string; resource_id: string | null;
  actor_name: string; summary: string; created_at: string;
}
export interface Notification { id: string; task_id: string | null; title: string; message: string; is_read: boolean; created_at: string }
export interface Job {
  id: string; kind: string; status: 'queued' | 'running' | 'succeeded' | 'failed';
  store_id: string | null; created_at: string; started_at: string | null; finished_at: string | null;
  attempts: number; error_message: string | null; result: unknown;
}
export interface Attachment { id: string; filename: string; content_type: string; size_bytes: number; store_id: string | null; created_at: string }
export interface Workspace {
  store_count: number; user_count: number | null; pending_jobs: number; unread_notifications: number;
  recent_activity: Audit[]; data_status: { orders: null; advertising: null; inventory: null }; environment: string;
}
export interface ListResult<T> { items: T[]; total: number }
