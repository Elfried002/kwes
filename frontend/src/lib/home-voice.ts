/**
 * Orchestration de la réponse parlée de l'accueil (pure, testable).
 *
 * L'accueil n'affiche pas de bloc de texte : Kwes répond avec sa voix, et le
 * sous-titre ne montre que la phrase réellement en train d'être prononcée,
 * révélée au rythme de la lecture. Cet automate décrit ce qui est su et quand :
 *
 *   idle ──SEND──▶ thinking ──PLAYING──▶ speaking ──SPOKEN (fin de tour)──▶ idle
 *                    │                      │
 *                    └──────ERROR──────────▶ error ──SEND──▶ thinking
 *
 * Les événements viennent de faits observés, jamais d'un minuteur :
 * `PLAYING` est émis quand l'audio (ou la voix de l'appareil) démarre
 * réellement, `PROGRESS` à la position réelle de lecture, `SPOKEN` à la fin
 * réelle de la phrase.
 */

import { revealCaption } from './kwes-speech';

export type HomeVoicePhase = 'idle' | 'thinking' | 'speaking' | 'error';

export interface HomeVoiceState {
  phase: HomeVoicePhase;
  /** Réponse complète reçue du flux — jamais affichée en bloc. */
  answer: string;
  /** Phrase en cours de lecture : c'est elle, et elle seule, qui s'affiche. */
  sentence: string;
  /** Part de cette phrase déjà prononcée (0..1), mesurée sur la lecture réelle. */
  progress: number;
  /** Phrases envoyées en synthèse. */
  sentences: number;
  /** Phrases dont la lecture est réellement terminée. */
  spoken: number;
  /** Phrases en attente de lecture. */
  pending: number;
  /** Conversation côté serveur, pour « Lire la réponse ». */
  conversationId: string | null;
  /** Flux SSE encore ouvert. */
  streaming: boolean;
  error: string | null;
}

export type HomeVoiceEvent =
  | { type: 'SEND' }
  | { type: 'DELTA'; text: string }
  | { type: 'SENTENCE'; text: string }
  | { type: 'PLAYING'; text: string }
  | { type: 'PROGRESS'; text: string; fraction: number }
  | { type: 'SPOKEN'; text: string }
  | { type: 'CONVERSATION'; id: string | null }
  | { type: 'DONE'; conversationId?: string | null }
  | { type: 'STOP' }
  | { type: 'ERROR'; message: string };

export const initialHomeVoice: HomeVoiceState = {
  phase: 'idle',
  answer: '',
  sentence: '',
  progress: 0,
  sentences: 0,
  spoken: 0,
  pending: 0,
  conversationId: null,
  streaming: false,
  error: null,
};

export function reduceHomeVoice(state: HomeVoiceState, event: HomeVoiceEvent): HomeVoiceState {
  switch (event.type) {
    case 'SEND':
      return {
        ...initialHomeVoice,
        phase: 'thinking',
        streaming: true,
      };

    case 'DELTA':
      return { ...state, answer: state.answer + event.text };

    case 'SENTENCE': {
      if (!event.text.trim()) return state;
      return { ...state, sentences: state.sentences + 1, pending: state.pending + 1 };
    }

    case 'PLAYING':
      // La voix démarre vraiment : c'est le seul fait qui autorise « speaking ».
      return {
        ...state,
        phase: 'speaking',
        sentence: event.text,
        progress: 0,
        error: null,
      };

    case 'PROGRESS': {
      if (event.text !== state.sentence) return state; // phrase déjà remplacée
      const fraction = Number.isFinite(event.fraction) ? event.fraction : 0;
      return { ...state, progress: Math.max(state.progress, Math.min(1, fraction)) };
    }

    case 'SPOKEN': {
      // Fin d'une phrase : s'il en reste une à lire, la bouche ne se referme pas
      // entre deux phrases (aucun clignotement d'état).
      const already = event.text === state.sentence;
      const pending = Math.max(0, state.pending - (already ? 1 : 0));
      const remaining = pending > 0 || state.streaming;
      return {
        ...state,
        pending,
        spoken: state.spoken + 1,
        progress: already ? 1 : state.progress,
        phase: remaining ? state.phase : 'idle',
      };
    }

    case 'CONVERSATION':
      return { ...state, conversationId: event.id };

    case 'DONE': {
      const conversationId = event.conversationId ?? state.conversationId;
      if (!state.answer.trim() && !state.sentence.trim()) {
        return {
          ...state,
          conversationId,
          streaming: false,
          phase: 'error',
          error: 'Aucune réponse n’est revenue. Réessayez.',
        };
      }
      return {
        ...state,
        conversationId,
        streaming: false,
        phase: state.pending > 0 || state.phase === 'speaking' ? state.phase : 'idle',
      };
    }

    case 'STOP':
      return {
        ...initialHomeVoice,
        conversationId: state.conversationId,
      };

    case 'ERROR':
      return {
        ...state,
        phase: 'error',
        streaming: false,
        pending: 0,
        error: event.message,
      };

    default:
      return state;
  }
}

/** Le sous-titre : la phrase en cours, révélée au rythme de la parole. */
export function homeCaption(state: HomeVoiceState): string {
  if (state.error) return state.error;
  return revealCaption(state.sentence, state.progress);
}

/** La phrase entière prononcée — pour les lecteurs d'écran (annonce stable). */
export function homeSpokenLine(state: HomeVoiceState): string {
  // Les erreurs sont annoncées une seule fois, par la région de statut.
  if (state.error) return '';
  return state.sentence;
}

/** Le lien « Lire la réponse » n'apparaît que si la conversation existe. */
export function canReadAnswer(state: HomeVoiceState): boolean {
  if (!state.conversationId) return false;
  if (state.streaming) return false;
  return Boolean(state.answer.trim() || state.sentence.trim());
}

/** Annonce aria-live : courte, stable, jamais la révélation mot à mot. */
export function homeAnnouncement(state: HomeVoiceState): string {
  switch (state.phase) {
    case 'thinking':
      return 'Kwes prépare sa réponse.';
    case 'speaking':
      return 'Kwes répond à voix haute.';
    case 'error':
      return state.error ?? 'La réponse n’a pas abouti.';
    default:
      return state.sentence ? 'Réponse terminée.' : '';
  }
}
