import { getToken, type Session } from './auth';
import type {
  ApiErrorShape,
  Approval,
  ChatRequest,
  ChatResponse,
  Conversation,
  Health,
  Integration,
  MemoryItem,
  Message,
  Notification,
  Skill,
  Task,
  TaskDetail,
} from './types';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'
).replace(/\/+$/, '');

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly details?: unknown;
  readonly requestId?: string;

  constructor(params: {
    message: string;
    code?: string;
    status?: number;
    retryable?: boolean;
    details?: unknown;
    requestId?: string;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.code = params.code ?? 'INTERNAL';
    this.status = params.status ?? 0;
    this.retryable = params.retryable ?? false;
    this.details = params.details;
    this.requestId = params.requestId;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function errorMessage(value: unknown): string {
  if (isApiError(value)) return value.message;
  if (value instanceof Error) return value.message;
  if (typeof value === 'string') return value;
  return 'Une erreur inattendue est survenue.';
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  auth?: boolean;
  timeoutMs?: number;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function normalizeError(payload: unknown, status: number): ApiError {
  if (payload && typeof payload === 'object' && 'error' in payload) {
    const shape = payload as ApiErrorShape;
    const error = shape.error;
    if (error && typeof error === 'object') {
      return new ApiError({
        message: typeof error.message === 'string' ? error.message : 'Requête refusée par le serveur.',
        code: typeof error.code === 'string' ? error.code : 'INTERNAL',
        status,
        retryable: error.retryable === true,
        details: error.details,
        requestId: typeof error.request_id === 'string' ? error.request_id : undefined,
      });
    }
  }
  if (typeof payload === 'string' && payload.trim()) {
    return new ApiError({ message: payload.slice(0, 300), code: 'INTERNAL', status });
  }
  return new ApiError({
    message:
      status === 401
        ? 'Session expirée ou invalide.'
        : status === 403
          ? 'Accès refusé.'
          : status === 404
            ? 'Ressource introuvable.'
            : `Le serveur a répondu ${status}.`,
    code:
      status === 401
        ? 'UNAUTHENTICATED'
        : status === 403
          ? 'FORBIDDEN'
          : status === 404
            ? 'NOT_FOUND'
            : 'INTERNAL',
    status,
    retryable: status >= 500,
  });
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, auth = true, timeoutMs = 25_000 } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };

  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth) {
    const token = getToken();
    if (!token) {
      throw new ApiError({
        message: 'Vous devez être connecté pour effectuer cette action.',
        code: 'UNAUTHENTICATED',
        status: 401,
      });
    }
    headers.Authorization = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = (): void => controller.abort();
  signal?.addEventListener('abort', abortFromCaller, { once: true });

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: 'omit',
      cache: 'no-store',
    });
  } catch (cause) {
    if (signal?.aborted) {
      throw new ApiError({ message: 'Requête annulée.', code: 'ABORTED', status: 0 });
    }
    throw new ApiError({
      message:
        controller.signal.aborted
          ? "Le serveur n'a pas répondu dans le délai imparti."
          : `Backend injoignable (${API_BASE_URL}). Vérifie que le serveur est démarré.`,
      code: 'NETWORK',
      status: 0,
      retryable: true,
      details: cause instanceof Error ? cause.name : undefined,
    });
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener('abort', abortFromCaller);
  }

  const payload = await parseBody(response);

  if (!response.ok) {
    const error = normalizeError(payload, response.status);
    if (response.status === 401 && auth) {
      window.dispatchEvent(new CustomEvent('kwes:unauthorized'));
    }
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return payload as T;
}

function asArray<T>(payload: unknown, key: string): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const candidate = record[key] ?? record.items ?? record.data;
    if (Array.isArray(candidate)) return candidate as T[];
  }
  return [];
}

/* ---------- Health ---------- */

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return request<Health>('/health', { auth: false, signal, timeoutMs: 8000 });
}

/* ---------- Conversations ---------- */

export function listConversations(signal?: AbortSignal): Promise<Conversation[]> {
  return request<unknown>('/conversations', { signal }).then((payload) =>
    asArray<Conversation>(payload, 'conversations'),
  );
}

export function createConversation(
  input: { title?: string; language?: string } = {},
  signal?: AbortSignal,
): Promise<Conversation> {
  return request<Conversation>('/conversations', { method: 'POST', body: input, signal });
}

export function getConversation(id: string, signal?: AbortSignal): Promise<Conversation> {
  return request<Conversation>(`/conversations/${encodeURIComponent(id)}`, { signal });
}

export function deleteConversation(id: string, signal?: AbortSignal): Promise<void> {
  return request<void>(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE', signal });
}

export function listMessages(conversationId: string, signal?: AbortSignal): Promise<Message[]> {
  return request<unknown>(`/conversations/${encodeURIComponent(conversationId)}/messages`, {
    signal,
  }).then((payload) => asArray<Message>(payload, 'messages'));
}

/* ---------- Chat ---------- */

export function sendChat(input: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>('/chat', {
    method: 'POST',
    body: input,
    signal,
    timeoutMs: 120_000,
  });
}

/* ---------- Tasks ---------- */

export function listTasks(signal?: AbortSignal): Promise<Task[]> {
  return request<unknown>('/tasks', { signal }).then((payload) => asArray<Task>(payload, 'tasks'));
}

export function getTask(id: string, signal?: AbortSignal): Promise<TaskDetail> {
  return request<TaskDetail>(`/tasks/${encodeURIComponent(id)}`, { signal });
}

export function cancelTask(id: string, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST', signal });
}

export function pauseTask(id: string, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(`/tasks/${encodeURIComponent(id)}/pause`, { method: 'POST', signal });
}

export function resumeTask(id: string, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(`/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST', signal });
}

/* ---------- Approvals ---------- */

export function listApprovals(signal?: AbortSignal): Promise<Approval[]> {
  return request<unknown>('/approvals', { signal }).then((payload) =>
    asArray<Approval>(payload, 'approvals'),
  );
}

export function approveRequest(id: string, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(`/approvals/${encodeURIComponent(id)}/approve`, {
    method: 'POST',
    signal,
  });
}

export function rejectRequest(id: string, signal?: AbortSignal): Promise<unknown> {
  return request<unknown>(`/approvals/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    signal,
  });
}

/* ---------- Lecture seule ---------- */

export function listSkills(signal?: AbortSignal): Promise<Skill[]> {
  return request<unknown>('/skills', { signal }).then((payload) => asArray<Skill>(payload, 'skills'));
}

export function listMemory(signal?: AbortSignal): Promise<MemoryItem[]> {
  return request<unknown>('/memory', { signal }).then((payload) =>
    asArray<MemoryItem>(payload, 'memories'),
  );
}

export function listNotifications(signal?: AbortSignal): Promise<Notification[]> {
  return request<unknown>('/notifications', { signal }).then((payload) =>
    asArray<Notification>(payload, 'notifications'),
  );
}

/** Non exposé dans les contrats P0 : l'écran Réglages affiche l'absence proprement. */
export function listIntegrations(signal?: AbortSignal): Promise<Integration[]> {
  return request<unknown>('/integrations', { signal, timeoutMs: 10_000 }).then((payload) =>
    asArray<Integration>(payload, 'integrations'),
  );
}

export type { Session };
