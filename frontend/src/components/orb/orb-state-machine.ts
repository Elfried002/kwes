/**
 * Machine à états de l'Hybrid Orb.
 *
 * Source de vérité : CONTRACTS.md — « Mapping événements → états de l'Orb ».
 * Aucun état n'est déduit du texte du LLM : seuls les événements explicites
 * (requête en vol, événements WS, erreurs API, lecture audio) pilotent la machine.
 *
 * La fonction `transition` est pure : même (état, événement) ⇒ même résultat.
 * Une transition non déclarée est un no-op signalé par `changed: false`.
 */

export const ORB_STATES = [
  'idle',
  'listening',
  'thinking',
  'executing',
  'speaking',
  'response',
  'success',
  'error',
  'waiting_approval',
] as const;

export type OrbState = (typeof ORB_STATES)[number];

export const ORB_EVENTS = [
  /** Micro activé côté client. */
  'MIC_START',
  /** Micro coupé côté client. */
  'MIC_STOP',
  /** POST /chat en vol. */
  'CHAT_SUBMITTED',
  /** Réponse assistant affichée. */
  'CHAT_RESPONSE',
  /** task.updated status=running. */
  'TASK_RUNNING',
  /** task.step.started. */
  'TASK_STEP_STARTED',
  /** task.awaiting_approval. */
  'TASK_AWAITING_APPROVAL',
  /** task.updated status=completed. */
  'TASK_COMPLETED',
  /** task.failed. */
  'TASK_FAILED',
  /** Erreur API (réseau, 4xx/5xx, session). */
  'API_ERROR',
  /** Lecture audio réelle démarrée. */
  'AUDIO_START',
  /** Lecture audio terminée. */
  'AUDIO_END',
  /** L'utilisateur a approuvé ou refusé une demande. */
  'APPROVAL_DECIDED',
  /** Retour explicite à l'état neutre. */
  'RESET',
  /** Fin du délai de 2 s après un succès. */
  'TIMEOUT',
] as const;

export type OrbEventType = (typeof ORB_EVENTS)[number];

export interface OrbEvent {
  type: OrbEventType;
  /** Identifiant de mission associé lorsque l'événement vient du WS. */
  taskId?: string;
  /** Message lisible pour l'interface (jamais du texte LLM brut). */
  detail?: string;
}

export interface OrbTransition {
  state: OrbState;
  changed: boolean;
  /** État à restaurer après `AUDIO_END` (renseigné à l'entrée en `speaking`). */
  resumeFrom: OrbState | null;
}

type TransitionTable = Record<OrbState, Partial<Record<OrbEventType, OrbState>>>;

/**
 * Table de transitions. Volontairement conservatrice :
 * - `error` n'est quitté que par une action utilisateur ou une nouvelle requête ;
 * - `thinking` n'accepte pas `MIC_START` (une requête est déjà en vol) ;
 * - `executing` ne bascule pas sur `CHAT_RESPONSE` (la mission reste prioritaire) ;
 * - `waiting_approval` ne se résout que par décision ou événement serveur.
 */
export const TRANSITIONS: TransitionTable = {
  idle: {
    MIC_START: 'listening',
    CHAT_SUBMITTED: 'thinking',
    CHAT_RESPONSE: 'response',
    TASK_RUNNING: 'executing',
    TASK_STEP_STARTED: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    AUDIO_START: 'speaking',
    RESET: 'idle',
  },
  listening: {
    MIC_STOP: 'idle',
    CHAT_SUBMITTED: 'thinking',
    API_ERROR: 'error',
    TASK_FAILED: 'error',
    RESET: 'idle',
  },
  thinking: {
    CHAT_RESPONSE: 'response',
    TASK_RUNNING: 'executing',
    TASK_STEP_STARTED: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    AUDIO_START: 'speaking',
    RESET: 'idle',
  },
  executing: {
    TASK_RUNNING: 'executing',
    TASK_STEP_STARTED: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    AUDIO_START: 'speaking',
    RESET: 'idle',
  },
  speaking: {
    AUDIO_END: 'response',
    MIC_START: 'listening',
    TASK_RUNNING: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    RESET: 'idle',
  },
  response: {
    CHAT_SUBMITTED: 'thinking',
    MIC_START: 'listening',
    TASK_RUNNING: 'executing',
    TASK_STEP_STARTED: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    AUDIO_START: 'speaking',
    RESET: 'idle',
  },
  success: {
    TIMEOUT: 'idle',
    RESET: 'idle',
    MIC_START: 'listening',
    CHAT_SUBMITTED: 'thinking',
    TASK_RUNNING: 'executing',
    TASK_STEP_STARTED: 'executing',
    TASK_AWAITING_APPROVAL: 'waiting_approval',
    API_ERROR: 'error',
  },
  error: {
    RESET: 'idle',
    MIC_START: 'listening',
    CHAT_SUBMITTED: 'thinking',
    TASK_RUNNING: 'executing',
    CHAT_RESPONSE: 'response',
  },
  waiting_approval: {
    APPROVAL_DECIDED: 'thinking',
    TASK_RUNNING: 'executing',
    TASK_COMPLETED: 'success',
    TASK_FAILED: 'error',
    API_ERROR: 'error',
    RESET: 'idle',
  },
};

export function isOrbState(value: unknown): value is OrbState {
  return typeof value === 'string' && (ORB_STATES as readonly string[]).includes(value);
}

export function canTransition(state: OrbState, event: OrbEventType): boolean {
  return TRANSITIONS[state][event] !== undefined || (state === 'speaking' && event === 'AUDIO_END');
}

/**
 * @param state état courant
 * @param event événement explicite
 * @param resumeFrom état à restaurer en sortie de `speaking` (fourni par l'appelant)
 */
export function transition(
  state: OrbState,
  event: OrbEventType,
  resumeFrom: OrbState | null = null,
): OrbTransition {
  if (state === 'speaking' && event === 'AUDIO_END') {
    const target = resumeFrom && resumeFrom !== 'speaking' ? resumeFrom : 'response';
    return { state: target, changed: true, resumeFrom: null };
  }

  const target = TRANSITIONS[state][event];

  if (!target) {
    return { state, changed: false, resumeFrom };
  }

  if (target === 'speaking') {
    return {
      state: 'speaking',
      changed: true,
      resumeFrom: state,
    };
  }

  return {
    state: target,
    changed: target !== state,
    resumeFrom: target === 'idle' ? null : resumeFrom,
  };
}

export function reduce(state: OrbState, events: readonly OrbEvent[]): OrbState {
  let current = state;
  let resume: OrbState | null = null;
  for (const event of events) {
    const result = transition(current, event.type, resume);
    current = result.state;
    resume = result.resumeFrom;
  }
  return current;
}

export interface OrbStateMeta {
  /** Libellé visible (DESIGN_SYSTEM.md §6). */
  label: string;
  /** Phrase annoncée via aria-live. */
  announcement: string;
  /** Indication contextuelle sous l'Orb. */
  caption: string;
  /** Couleur d'accent (token CSS). */
  tone: 'neutral' | 'accent' | 'cyan' | 'success' | 'warning' | 'danger' | 'violet';
  /** Le son est-il réellement en cours de lecture ? */
  audio: boolean;
  /** Doit-on afficher un écran/ordinateur dans l'Orb ? */
  device: boolean;
}

export const ORB_STATE_META: Record<OrbState, OrbStateMeta> = {
  idle: {
    label: 'Prêt',
    announcement: 'Kwes est prêt.',
    caption: 'Kwes est prêt. Écrivez ou activez le micro.',
    tone: 'cyan',
    audio: false,
    device: false,
  },
  listening: {
    label: 'Écoute',
    announcement: 'Kwes écoute.',
    caption: 'Micro actif — parlez, puis coupez le micro pour envoyer.',
    tone: 'cyan',
    audio: false,
    device: false,
  },
  thinking: {
    label: 'Réflexion',
    announcement: 'Kwes réfléchit.',
    caption: 'Kwes analyse votre demande…',
    tone: 'accent',
    audio: false,
    device: false,
  },
  executing: {
    label: 'Exécution',
    announcement: 'Kwes exécute une mission.',
    caption: 'Mission en cours — les étapes et la progression sont réelles.',
    tone: 'accent',
    audio: false,
    device: true,
  },
  speaking: {
    label: 'Parle',
    announcement: 'Kwes parle.',
    caption: 'Lecture audio en cours. Vous pouvez interrompre.',
    tone: 'violet',
    audio: true,
    device: false,
  },
  response: {
    label: 'Réponse',
    announcement: 'Kwes a répondu.',
    caption: 'Réponse affichée. Vous pouvez poursuivre ou copier.',
    tone: 'cyan',
    audio: false,
    device: false,
  },
  success: {
    label: 'Terminé',
    announcement: 'Mission terminée.',
    caption: 'Mission terminée avec confirmation du serveur.',
    tone: 'success',
    audio: false,
    device: false,
  },
  error: {
    label: 'Incident',
    announcement: "Une erreur s'est produite.",
    caption: 'Incident signalé. Aucune action n’est déclarée réussie.',
    tone: 'danger',
    audio: false,
    device: false,
  },
  waiting_approval: {
    label: 'Validation requise',
    announcement: 'Kwes attend votre validation.',
    caption: 'Une action attend votre approbation avant de continuer.',
    tone: 'warning',
    audio: false,
    device: false,
  },
};
