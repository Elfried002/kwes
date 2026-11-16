import { API_BASE_URL } from './api';
import type { WsEnvelope } from './types';

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting' | 'offline' | 'unauthorized';

export function buildWsUrl(token: string): string {
  const base = new URL(API_BASE_URL);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  base.pathname = `${base.pathname.replace(/\/+$/, '')}/ws`;
  base.search = '';
  base.searchParams.set('token', token);
  return base.toString();
}

interface KwesSocketOptions {
  onEnvelope: (envelope: WsEnvelope) => void;
  onStatus: (status: ConnectionStatus, attempt: number) => void;
  onOpen?: () => void;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;
const HEARTBEAT_MS = 25_000;

/** Reconnexion avec backoff exponentiel plafonné + jitter. Le WS n'est jamais source de vérité. */
export class KwesSocket {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private retryTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private stopped = false;
  private readonly token: string;
  private readonly options: KwesSocketOptions;

  constructor(token: string, options: KwesSocketOptions) {
    this.token = token;
    this.options = options;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.socket?.close(1000, 'client stop');
    this.socket = null;
  }

  private clearTimers(): void {
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private connect(): void {
    if (this.stopped) return;
    this.options.onStatus(this.attempt === 0 ? 'connecting' : 'reconnecting', this.attempt);

    let socket: WebSocket;
    try {
      socket = new WebSocket(buildWsUrl(this.token));
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      if (this.stopped) return;
      this.attempt = 0;
      this.options.onStatus('open', 0);
      this.options.onOpen?.();
      this.heartbeatTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ event: 'ping', timestamp: new Date().toISOString() }));
        }
      }, HEARTBEAT_MS);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      if (typeof event.data !== 'string') return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      if (typeof parsed !== 'object' || parsed === null) return;
      const envelope = parsed as Partial<WsEnvelope>;
      if (typeof envelope.event !== 'string') return;
      if (envelope.event === 'pong') return;
      this.options.onEnvelope({
        event: envelope.event,
        event_id: typeof envelope.event_id === 'string' ? envelope.event_id : '',
        timestamp: typeof envelope.timestamp === 'string' ? envelope.timestamp : new Date().toISOString(),
        data: (envelope.data ?? {}) as Record<string, unknown>,
      });
    };

    socket.onerror = () => {
      // onclose suit et déclenche le backoff.
    };

    socket.onclose = (event: CloseEvent) => {
      this.clearTimers();
      this.socket = null;
      if (this.stopped) return;
      if (event.code === 4401 || event.code === 4403 || event.code === 1008) {
        this.options.onStatus('unauthorized', this.attempt);
        this.stopped = true;
        return;
      }
      this.options.onStatus('offline', this.attempt);
      this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    if (this.stopped) return;
    const exponential = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** this.attempt);
    const jitter = exponential * (0.75 + Math.random() * 0.5);
    this.attempt += 1;
    this.retryTimer = window.setTimeout(() => this.connect(), jitter);
  }
}
