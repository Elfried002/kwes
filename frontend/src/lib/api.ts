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

export interface DownloadedFile {
  blob: Blob;
  filename: string;
}

/**
 * Télécharge un document produit par Kwes. Le fichier est privé : la requête
 * porte le jeton de session, un simple lien ne suffirait pas.
 */
export async function downloadDocument(id: string): Promise<DownloadedFile> {
  const token = getToken();
  if (!token) {
    throw new ApiError({
      message: 'Vous devez être connecté pour ouvrir ce document.',
      code: 'UNAUTHENTICATED',
      status: 401,
    });
  }
  const response = await fetch(`${API_BASE_URL}/documents/${id}/download`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: 'omit',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw normalizeError(await parseBody(response), response.status);
  }
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? 'document.txt' };
}

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

export interface ChatStreamInput {
  conversation_id?: string | null;
  message: string;
  language?: string;
  mode?: 'auto' | 'direct' | 'mission';
}

export interface ChatStreamMeta {
  conversation_id?: string;
  message_id?: string;
}

export interface ChatStreamDone {
  conversation_id?: string;
  message_id?: string;
  response?: string;
  intent?: string;
  status?: string;
  task_id?: string | null;
  mock?: boolean;
}

export interface ChatStreamHandlers {
  onMeta?: (meta: ChatStreamMeta) => void;
  onDelta: (text: string, meta: ChatStreamMeta) => void;
  onDone?: (payload: ChatStreamDone) => void;
  /** Événement `error` émis par le serveur (après ouverture du flux). */
  onError?: (error: ApiError) => void;
}

function parseSseBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    const parsed: unknown = JSON.parse(dataLines.join('\n'));
    if (!parsed || typeof parsed !== 'object') return null;
    return { event, data: parsed as Record<string, unknown> };
  } catch {
    return null;
  }
}

/**
 * POST /chat/stream : lit le flux SSE et appelle les callbacks au fil de l'eau.
 * Ne lève pas pour un `error` applicatif (rapporté via `onError`) ; lève
 * seulement pour un échec réseau/HTTP avant l'ouverture du flux.
 */
export async function streamChat(
  input: ChatStreamInput,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  if (!token) {
    throw new ApiError({
      message: 'Vous devez être connecté pour effectuer cette action.',
      code: 'UNAUTHENTICATED',
      status: 401,
    });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        conversation_id: input.conversation_id ?? null,
        message: input.message,
        language: input.language ?? null,
        mode: input.mode ?? 'auto',
      }),
      signal,
      credentials: 'omit',
      cache: 'no-store',
    });
  } catch (cause) {
    if (signal?.aborted) {
      throw new ApiError({ message: 'Requête annulée.', code: 'ABORTED', status: 0 });
    }
    throw new ApiError({
      message: `Backend injoignable (${API_BASE_URL}). Vérifie que le serveur est démarré.`,
      code: 'NETWORK',
      status: 0,
      retryable: true,
      details: cause instanceof Error ? cause.name : undefined,
    });
  }

  if (!response.ok) {
    const payload = await parseBody(response);
    const error = normalizeError(payload, response.status);
    if (response.status === 401) window.dispatchEvent(new CustomEvent('kwes:unauthorized'));
    throw error;
  }
  if (!response.body) {
    throw new ApiError({ message: 'Flux de réponse indisponible.', code: 'STREAM_UNAVAILABLE', status: 0 });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const frame = parseSseBlock(block);
        if (frame) {
          const meta: ChatStreamMeta = {
            conversation_id:
              typeof frame.data.conversation_id === 'string' ? frame.data.conversation_id : undefined,
            message_id: typeof frame.data.message_id === 'string' ? frame.data.message_id : undefined,
          };
          if (frame.event === 'delta') {
            if (meta.conversation_id) handlers.onMeta?.(meta);
            const delta = typeof frame.data.delta === 'string' ? frame.data.delta : '';
            if (delta) handlers.onDelta(delta, meta);
          } else if (frame.event === 'done') {
            if (meta.conversation_id) handlers.onMeta?.(meta);
            handlers.onDone?.({
              conversation_id: meta.conversation_id,
              message_id: meta.message_id,
              response: typeof frame.data.response === 'string' ? frame.data.response : undefined,
              intent: typeof frame.data.intent === 'string' ? frame.data.intent : undefined,
              status: typeof frame.data.status === 'string' ? frame.data.status : undefined,
              task_id: typeof frame.data.task_id === 'string' ? frame.data.task_id : null,
              mock: frame.data.mock === true,
            });
          } else if (frame.event === 'error') {
            handlers.onError?.(
              new ApiError({
                message:
                  typeof frame.data.message === 'string'
                    ? frame.data.message
                    : 'Le flux de réponse a échoué.',
                code: typeof frame.data.code === 'string' ? frame.data.code : 'STREAM_ERROR',
                status: 0,
                retryable: frame.data.retryable !== false,
              }),
            );
          }
        }
        boundary = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/* ---------- Voix ---------- */

export interface SynthesizedSpeech {
  text: string;
  audioBase64: string | null;
  mimeType: string | null;
  fallback: boolean;
  reason?: string | null;
  voiceId?: string | null;
  mock: boolean;
}

/** POST /voice/synthesize — audio base64 ElevenLabs, repli texte explicite. */
export async function synthesizeSpeech(
  text: string,
  signal?: AbortSignal,
  voiceId?: string | null,
): Promise<SynthesizedSpeech> {
  const payload = await request<{
    text?: string;
    audio_base64?: string | null;
    mime_type?: string | null;
    fallback?: boolean;
    reason?: string | null;
    voice_id?: string | null;
    mock?: boolean;
  }>('/voice/synthesize', {
    method: 'POST',
    body: voiceId ? { text, voice_id: voiceId } : { text },
    signal,
    timeoutMs: 45_000,
  });

  return {
    text: typeof payload.text === 'string' ? payload.text : text,
    audioBase64: typeof payload.audio_base64 === 'string' ? payload.audio_base64 : null,
    mimeType: typeof payload.mime_type === 'string' ? payload.mime_type : null,
    fallback: payload.fallback !== false,
    reason: typeof payload.reason === 'string' ? payload.reason : null,
    voiceId: typeof payload.voice_id === 'string' ? payload.voice_id : null,
    mock: payload.mock === true,
  };
}

export interface VoiceOption {
  id: string;
  name: string;
  gender: string | null;
  language: string | null;
  accent: string | null;
  description: string | null;
  previewUrl?: string | null;
}

export interface VoiceCatalog {
  voices: VoiceOption[];
  mock: boolean;
  cached: boolean;
  reason: string | null;
  defaultVoiceId: string | null;
}

function normalizeVoice(raw: unknown): VoiceOption | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  const id = typeof item.id === 'string' ? item.id.trim() : '';
  if (!id) return null;
  const text = (value: unknown): string | null =>
    typeof value === 'string' && value.trim() ? value.trim() : null;
  return {
    id,
    name: text(item.name) ?? id,
    gender: text(item.gender),
    language: text(item.language),
    accent: text(item.accent),
    description: text(item.description),
    previewUrl: text(item.preview_url ?? item.previewUrl),
  };
}

/** GET /voice/voices — catalogue des voix disponibles pour les réglages. */
export async function listVoices(signal?: AbortSignal): Promise<VoiceCatalog> {
  const payload = await request<{
    voices?: unknown;
    mock?: boolean;
    cached?: boolean;
    reason?: string | null;
    default_voice_id?: string | null;
  }>('/voice/voices', { signal, timeoutMs: 12_000 });

  const voices = Array.isArray(payload.voices)
    ? payload.voices.map(normalizeVoice).filter((voice): voice is VoiceOption => voice !== null)
    : [];

  return {
    voices,
    mock: payload.mock === true,
    cached: payload.cached === true,
    reason: typeof payload.reason === 'string' ? payload.reason : null,
    defaultVoiceId: typeof payload.default_voice_id === 'string' ? payload.default_voice_id : null,
  };
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
