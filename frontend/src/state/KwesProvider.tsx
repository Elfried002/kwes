import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { getHealth } from '../lib/api';
import { useSession } from '../lib/auth';
import { errorMessage } from '../lib/api';
import { KwesSocket, type ConnectionStatus } from '../lib/ws';
import type { Health, TaskEventData, WsEnvelope } from '../lib/types';
import { orbEventFromEnvelope, type OrbMachineAction } from '../lib/orb-events';
import {
  ORB_STATE_META,
  transition,
  type OrbEventType,
  type OrbState,
  type OrbStateMeta,
} from '../components/orb/orb-state-machine';

export type UiConnection = 'idle' | 'connecting' | 'online' | 'reconnecting' | 'offline' | 'unauthorized';
export type ServerStatus = 'unknown' | 'ok' | 'degraded' | 'unreachable';

interface MachineSnapshot {
  state: OrbState;
  resumeFrom: OrbState | null;
  lastTaskId: string | null;
  lastDetail: string | null;
}

type MachineAction = OrbMachineAction;

function machineReducer(previous: MachineSnapshot, action: MachineAction): MachineSnapshot {
  const result = transition(previous.state, action.type, previous.resumeFrom);
  if (!result.changed && action.taskId === undefined && action.detail === undefined) {
    return previous;
  }
  return {
    state: result.state,
    resumeFrom: result.resumeFrom,
    lastTaskId: action.taskId ?? previous.lastTaskId,
    lastDetail: action.detail ?? previous.lastDetail,
  };
}

/** Traduction pure des événements serveur → événements de la machine (CONTRACTS.md). */
interface KwesContextValue {
  orbState: OrbState;
  orbMeta: OrbStateMeta;
  lastTaskId: string | null;
  lastDetail: string | null;
  dispatchOrb: (type: OrbEventType, detail?: string, taskId?: string) => void;
  notifyChatStarted: () => void;
  notifyChatAnswered: () => void;
  notifyApiError: (cause: unknown) => void;
  notifyAudioStart: () => void;
  notifyAudioEnd: () => void;
  notifyApprovalDecided: (taskId?: string, outcome?: 'approved' | 'rejected') => void;
  resetOrb: () => void;
  micActive: boolean;
  setMicActive: (active: boolean) => void;
  connection: UiConnection;
  reconnectAttempt: number;
  serverStatus: ServerStatus;
  health: Health | null;
  lastError: string | null;
  clearError: () => void;
  events: WsEnvelope[];
  taskEvents: (taskId: string) => WsEnvelope[];
  subscribe: (listener: (envelope: WsEnvelope) => void) => () => void;
  refreshKey: number;
  bumpRefresh: () => void;
  probeHealth: () => void;
}

const KwesContext = createContext<KwesContextValue | null>(null);

export function KwesProvider({ children }: { children: ReactNode }) {
  const session = useSession();
  const [machine, dispatch] = useReducer(machineReducer, {
    state: 'idle',
    resumeFrom: null,
    lastTaskId: null,
    lastDetail: null,
  });
  const [connection, setConnection] = useState<UiConnection>('idle');
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [serverStatus, setServerStatus] = useState<ServerStatus>('unknown');
  const [health, setHealth] = useState<Health | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [events, setEvents] = useState<WsEnvelope[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [micActive, setMicActiveState] = useState(false);

  const pendingApprovals = useRef<Set<string>>(new Set());
  const refreshTimer = useRef<number | null>(null);
  const listeners = useRef<Set<(envelope: WsEnvelope) => void>>(new Set());
  const handlersRef = useRef<{ envelope: (envelope: WsEnvelope) => void } | null>(null);

  const bumpRefresh = useCallback(() => {
    if (refreshTimer.current !== null) return;
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      setRefreshKey((value) => value + 1);
    }, 350);
  }, []);

  const probeHealth = useCallback(() => {
    // Health est public : pas de jeton requis, pas de secret exposé.
    getHealth()
      .then((result) => {
        setHealth(result);
        setServerStatus(result.status === 'ok' ? 'ok' : 'degraded');
      })
      .catch(() => {
        setServerStatus('unreachable');
      });
  }, []);

  const dispatchOrb = useCallback((type: OrbEventType, detail?: string, taskId?: string) => {
    dispatch({ type, detail, taskId });
  }, []);

  const notifyApiError = useCallback((cause: unknown) => {
    setLastError(errorMessage(cause));
    dispatch({ type: 'API_ERROR' });
  }, []);

  const resetOrb = useCallback(() => {
    pendingApprovals.current.clear();
    dispatch({ type: 'RESET' });
  }, []);

  const notifyApprovalDecided = useCallback(
    (taskId?: string, outcome: 'approved' | 'rejected' = 'approved') => {
      if (taskId) pendingApprovals.current.delete(taskId);
      if (pendingApprovals.current.size > 0) {
        dispatch({ type: 'TASK_AWAITING_APPROVAL' });
      } else if (outcome === 'rejected') {
        dispatch({ type: 'RESET' });
      } else {
        dispatch({ type: 'APPROVAL_DECIDED', taskId });
      }
      bumpRefresh();
    },
    [bumpRefresh],
  );

  const setMicActive = useCallback((active: boolean) => {
    setMicActiveState(active);
    dispatch({ type: active ? 'MIC_START' : 'MIC_STOP' });
  }, []);

  const handleEnvelope = useCallback(
    (envelope: WsEnvelope) => {
      setEvents((previous) => [envelope, ...previous].slice(0, 150));

      const action = orbEventFromEnvelope(envelope);
      if (action) {
        if (action.type === 'TASK_AWAITING_APPROVAL' && action.taskId) {
          pendingApprovals.current.add(action.taskId);
        }
        if ((action.type === 'TASK_COMPLETED' || action.type === 'TASK_FAILED') && action.taskId) {
          pendingApprovals.current.delete(action.taskId);
        }

        // Une mission en attente de validation garde la priorité d'affichage.
        if (pendingApprovals.current.size > 0 && action.type !== 'TASK_AWAITING_APPROVAL') {
          dispatch({ type: 'TASK_AWAITING_APPROVAL' });
        } else {
          dispatch(action);
        }
        if (action.type === 'TASK_COMPLETED') setLastError(null);
      }

      if (envelope.event !== 'conversation.delta') bumpRefresh();

      for (const listener of listeners.current) listener(envelope);
    },
    [bumpRefresh],
  );
  handlersRef.current = { envelope: handleEnvelope };

  // Connexion WS + reconnexion backoff. REST reste la source de vérité.
  useEffect(() => {
    if (!session) {
      setConnection('idle');
      return;
    }
    setConnection('connecting');
    const socket = new KwesSocket(session.token, {
      onEnvelope: (envelope) => handlersRef.current?.envelope(envelope),
      onStatus: (status: ConnectionStatus, attempt: number) => {
        setReconnectAttempt(attempt);
        setConnection(status === 'open' ? 'online' : status);
      },
      onOpen: () => {
        setReconnectAttempt(0);
        probeHealth();
        bumpRefresh();
      },
    });
    socket.start();
    return () => socket.stop();
  }, [session?.token, probeHealth, bumpRefresh]);

  // Sonde de santé périodique + au retour d'onglet.
  useEffect(() => {
    probeHealth();
    const interval = window.setInterval(probeHealth, 45_000);
    const onVisible = (): void => {
      if (!document.hidden) {
        probeHealth();
        bumpRefresh();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [probeHealth, bumpRefresh]);

  // success → idle après 2 s (exigence du contrat).
  useEffect(() => {
    if (machine.state !== 'success') return;
    const timer = window.setTimeout(() => {
      if (pendingApprovals.current.size === 0) dispatch({ type: 'TIMEOUT' });
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [machine.state]);

  const subscribe = useCallback((listener: (envelope: WsEnvelope) => void) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  const taskEvents = useCallback(
    (taskId: string) =>
      events.filter((event) => {
        const data = (event.data ?? {}) as TaskEventData;
        return data.task_id === taskId;
      }),
    [events],
  );

  const value = useMemo<KwesContextValue>(
    () => ({
      orbState: machine.state,
      orbMeta: ORB_STATE_META[machine.state],
      lastTaskId: machine.lastTaskId,
      lastDetail: machine.lastDetail,
      dispatchOrb,
      notifyChatStarted: () => dispatch({ type: 'CHAT_SUBMITTED' }),
      notifyChatAnswered: () => dispatch({ type: 'CHAT_RESPONSE' }),
      notifyApiError,
      notifyAudioStart: () => dispatch({ type: 'AUDIO_START' }),
      notifyAudioEnd: () => dispatch({ type: 'AUDIO_END' }),
      notifyApprovalDecided,
      resetOrb,
      micActive,
      setMicActive,
      connection,
      reconnectAttempt,
      serverStatus,
      health,
      lastError,
      clearError: () => setLastError(null),
      events,
      taskEvents,
      subscribe,
      refreshKey,
      bumpRefresh,
      probeHealth,
    }),
    [
      machine,
      dispatchOrb,
      notifyApiError,
      notifyApprovalDecided,
      resetOrb,
      micActive,
      setMicActive,
      connection,
      reconnectAttempt,
      serverStatus,
      health,
      lastError,
      events,
      taskEvents,
      subscribe,
      refreshKey,
      bumpRefresh,
      probeHealth,
    ],
  );

  return <KwesContext.Provider value={value}>{children}</KwesContext.Provider>;
}

export function useKwes(): KwesContextValue {
  const context = useContext(KwesContext);
  if (!context) throw new Error('useKwes doit être utilisé dans <KwesProvider>.');
  return context;
}
