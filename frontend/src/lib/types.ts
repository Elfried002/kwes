/** Contrats de données Kwes (alignés sur docs/06-data/DATA_MODEL.md et CONTRACTS.md). */

export type TaskStatus =
  | 'queued'
  | 'planning'
  | 'awaiting_approval'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type StepStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'skipped';

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

export interface HealthDependencies {
  database?: string;
  redis?: string;
  llm?: string;
  [key: string]: string | undefined;
}

export interface Health {
  status: string;
  version?: string;
  dependencies?: HealthDependencies;
}

export interface Conversation {
  id: string;
  title: string | null;
  status: string;
  language?: string | null;
  created_at: string;
  updated_at: string;
  is_demo?: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  content_type?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
  is_demo?: boolean;
}

export interface ChatRequest {
  conversation_id: string | null;
  message: string;
  language: string;
  mode: 'auto' | 'text' | 'voice' | 'mission';
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  response: string;
  task_id?: string | null;
  status: TaskStatus | string;
}

export interface DocumentItem {
  id: string;
  title: string;
  format: string;
  chars: number;
  source?: string;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  conversation_id?: string | null;
  title: string;
  goal?: string | null;
  status: TaskStatus;
  priority?: string | null;
  progress: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  result_summary?: string | null;
  error_code?: string | null;
  is_demo?: boolean;
}

export interface TaskStep {
  id: string;
  task_id: string;
  step_key: string;
  title: string;
  skill_id?: string | null;
  status: StepStatus;
  input_json?: unknown;
  output_json?: unknown;
  attempt_count?: number | null;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail extends Task {
  steps: TaskStep[];
  events?: TaskEvent[];
}

export interface TaskEvent {
  id?: string;
  event?: string;
  created_at?: string;
  message?: string;
  data?: Record<string, unknown>;
}

export interface Approval {
  id: string;
  task_id: string;
  action_type: string;
  summary: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired' | string;
  payload_hash?: string | null;
  expires_at: string | null;
  decided_at?: string | null;
  is_demo?: boolean;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  current_version?: string | null;
  enabled: boolean;
  permissions?: string[] | null;
  last_tested_at?: string | null;
}

export interface MemoryItem {
  id: string;
  category: string;
  content: string;
  source_type?: string | null;
  confidence?: number | null;
  sensitivity?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  read_at: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  created_at: string;
}

export interface Integration {
  id: string;
  provider: string;
  status: string;
  scopes?: string[] | null;
  created_at?: string;
  updated_at?: string;
}

/* ---------- WebSocket ---------- */

export type WsEventName =
  | 'conversation.delta'
  | 'conversation.completed'
  | 'task.created'
  | 'task.updated'
  | 'task.step.started'
  | 'task.step.completed'
  | 'task.awaiting_approval'
  | 'task.failed'
  | 'notification.created'
  | 'system.status';

export interface WsEnvelope<T = Record<string, unknown>> {
  event: WsEventName | string;
  event_id: string;
  timestamp: string;
  data: T;
}

export interface TaskEventData {
  task_id?: string;
  status?: TaskStatus;
  progress?: number;
  step_id?: string;
  title?: string;
  error_code?: string;
  [key: string]: unknown;
}

export interface ConversationDeltaData {
  conversation_id?: string;
  message_id?: string;
  delta?: string;
  content?: string;
}

/* ---------- Divers ---------- */

export interface ApiErrorShape {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
    request_id?: string;
    retryable?: boolean;
  };
}

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  queued: 'En file',
  planning: 'Planification',
  awaiting_approval: 'Validation requise',
  running: 'En cours',
  paused: 'En pause',
  completed: 'Terminée',
  failed: 'Échouée',
  cancelled: 'Annulée',
};

export const STEP_STATUS_LABELS: Record<StepStatus, string> = {
  pending: 'En attente',
  ready: 'Prête',
  running: 'En cours',
  awaiting_approval: 'Validation',
  completed: 'Terminée',
  failed: 'Échouée',
  skipped: 'Ignorée',
};

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
