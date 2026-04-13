/** TypeScript types matching Cambium API response models. */

export type SessionOrigin = "system" | "user";
export type SessionStatus = "created" | "active" | "completed" | "failed";

export interface Session {
  id: string;
  origin: SessionOrigin;
  status: SessionStatus;
  routine_name: string | null;
  adapter_instance_name: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export type RequestType = "permission" | "information" | "preference";
export type RequestStatus = "pending" | "answered" | "expired" | "rejected";

export interface Request {
  id: string;
  session_id: string;
  work_item_id: string | null;
  type: RequestType;
  status: RequestStatus;
  summary: string;
  detail: string;
  options: string[] | null;
  default: string | null;
  timeout_hours: number | null;
  answer: string | null;
  created_at: string;
  answered_at: string | null;
  created_by: string | null;
}

export interface RequestSummary {
  counts: Record<string, Record<string, number>>;
}

export type WorkItemStatus =
  | "pending"
  | "ready"
  | "active"
  | "blocked"
  | "completed"
  | "failed"
  | "canceled";

export interface WorkItem {
  id: string;
  title: string;
  description: string;
  status: WorkItemStatus;
  parent_id: string | null;
  priority: number;
  completion_mode: "all" | "any";
  rollup_mode: "auto" | "synthesize";
  depends_on: string[];
  context: Record<string, unknown>;
  result: string | null;
  actor: string | null;
  assigned_to: string | null;
  session_id: string | null;
  max_attempts: number;
  attempt_count: number;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ListWorkItemsResponse {
  items: WorkItem[];
  total: number;
  limit: number;
  truncated: boolean;
}

export interface WorkItemEvent {
  id: string;
  item_id: string;
  event_type: string;
  actor: string | null;
  session_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  consumer_running: boolean;
  pending_messages: number;
  in_flight_messages: number;
}

export interface QueueStatus {
  pending: number;
  subscribed_channels: string[];
}

export interface ChannelEvent {
  id: string;
  timestamp: string;
  channel: string;
  source_session_id: string | null;
  payload: Record<string, unknown>;
}
