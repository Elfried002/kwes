/**
 * Machine à états de la conversation vocale continue (pure, testable).
 *
 * Aucun état n'est simulé : chaque transition est déclenchée par un fait
 * observable (micro réellement démarré, phrase réellement reconnue, flux SSE
 * réellement ouvert, audio réellement en lecture). Le rendu (Orb, annonces) se
 * contente de lire `phase`.
 *
 *   idle ──ACTIVATE──▶ listening ──UTTERANCE──▶ thinking ──AUDIO_PLAYING──▶ speaking
 *     ▲                    ▲                      │  ▲                        │
 *     │                    └──────AUDIO_ENDED─────┘  └────BARGE_IN────────────┘
 *     └──────────────────────────DEACTIVATE────────────────────────────────────┘
 */

export const VOICE_PHASES = ['idle', 'listening', 'thinking', 'speaking'] as const;
export type VoicePhase = (typeof VOICE_PHASES)[number];

export interface VoiceSessionState {
  phase: VoicePhase;
  /** Mode vocal activé par un clic explicite (aucune capture au chargement). */
  active: boolean;
  /** Veille : seules les phrases contenant le mot d'activation sont retenues. */
  standby: boolean;
  /** Écoute armée : les phrases sont envoyées sans mot d'activation. */
  armed: boolean;
  /** Transcription provisoire affichée pendant la parole. */
  pending: string;
  /** Réponse assistant reçue (deltas concaténés). */
  answer: string;
  /** Phrases en attente de lecture audio. */
  queued: number;
  /** Flux SSE encore ouvert. */
  streaming: boolean;
  error: string | null;
}

export type VoiceEvent =
  | { type: 'ACTIVATE' }
  | { type: 'DEACTIVATE' }
  | { type: 'STANDBY'; enabled: boolean }
  | { type: 'MIC_READY' }
  | { type: 'MIC_FAILED'; message: string }
  | { type: 'INTERIM'; text: string }
  | { type: 'WAKE_WORD' }
  | { type: 'UTTERANCE'; text: string }
  | { type: 'STREAM_START' }
  | { type: 'DELTA'; text: string }
  | { type: 'AUDIO_QUEUED' }
  | { type: 'AUDIO_PLAYING' }
  | { type: 'AUDIO_ENDED' }
  | { type: 'STREAM_DONE' }
  | { type: 'BARGE_IN' }
  | { type: 'STREAM_ERROR'; message: string }
  | { type: 'RESET' };

export const initialVoiceState: VoiceSessionState = {
  phase: 'idle',
  active: false,
  standby: false,
  armed: false,
  pending: '',
  answer: '',
  queued: 0,
  streaming: false,
  error: null,
};

/** Après la dernière phrase audio : on revient écouter si le mode est actif. */
function settle(state: VoiceSessionState): VoiceSessionState {
  if (state.streaming || state.queued > 0) return state;
  if (!state.active) return { ...state, phase: 'idle' };
  // En veille, chaque échange se referme : il faut redire « Kwes » pour le suivant.
  return { ...state, phase: 'listening', armed: state.standby ? false : state.armed };
}

export function reduceVoice(
  state: VoiceSessionState,
  event: VoiceEvent,
): VoiceSessionState {
  switch (event.type) {
    case 'ACTIVATE':
      if (state.active) return state;
      return {
        ...state,
        active: true,
        armed: !state.standby,
        phase: 'listening',
        pending: '',
        answer: '',
        error: null,
      };

    case 'DEACTIVATE':
      return {
        ...initialVoiceState,
        standby: state.standby,
      };

    case 'STANDBY':
      return { ...state, standby: event.enabled, armed: event.enabled ? false : state.armed };

    case 'MIC_READY':
      if (!state.active) return state;
      // Un redémarrage de la reconnaissance ne doit jamais interrompre un tour
      // en cours : sinon la phase repasserait à `listening` pendant que Kwes
      // parle, et plus rien ne pourrait couper l'audio.
      if (state.phase === 'thinking' || state.phase === 'speaking' || state.streaming) {
        return { ...state, error: null };
      }
      return { ...state, phase: 'listening', error: null };

    case 'MIC_FAILED':
      return { ...state, phase: 'idle', active: false, armed: false, error: event.message };

    case 'INTERIM':
      if (!state.active) return state;
      if (state.phase !== 'listening') return state;
      return { ...state, pending: event.text };

    case 'WAKE_WORD':
      if (!state.active) return state;
      return { ...state, armed: true, pending: '' };

    case 'UTTERANCE': {
      const text = event.text.trim();
      if (!text || !state.active) return state;
      // Une phrase pendant la lecture est un barge-in, pas un nouvel envoi :
      // le hook la transforme en BARGE_IN avant d'arriver ici.
      if (state.phase !== 'listening') return state;
      return {
        ...state,
        phase: 'thinking',
        pending: '',
        answer: '',
        streaming: true,
        queued: 0,
        error: null,
      };
    }

    case 'STREAM_START':
      if (!state.active) return state;
      return { ...state, streaming: true, phase: state.queued > 0 ? state.phase : 'thinking' };

    case 'DELTA':
      return { ...state, answer: state.answer + event.text };

    case 'AUDIO_QUEUED':
      return { ...state, queued: state.queued + 1 };

    case 'AUDIO_PLAYING':
      return { ...state, phase: 'speaking' };

    case 'AUDIO_ENDED':
      return settle({ ...state, queued: Math.max(0, state.queued - 1) });

    case 'STREAM_DONE':
      return settle({ ...state, streaming: false });

    case 'BARGE_IN':
      if (!state.active) return state;
      return {
        ...state,
        phase: 'listening',
        queued: 0,
        streaming: false,
        pending: '',
        answer: '',
      };

    case 'STREAM_ERROR':
      return {
        ...state,
        phase: state.active ? 'listening' : 'idle',
        streaming: false,
        queued: 0,
        answer: '',
        error: event.message,
      };

    case 'RESET':
      return { ...initialVoiceState, standby: state.standby };

    default:
      return state;
  }
}

/** L'audio doit-il être coupé immédiatement ? */
export function shouldCutAudio(state: VoiceSessionState): boolean {
  return state.phase === 'speaking' || state.queued > 0;
}

/* ------------------------------------------------------------------ */
/* Mot d'activation                                                    */
/* ------------------------------------------------------------------ */

/**
 * « Kwes », « Hey Kwes », « Ok Kwes » — avec les graphies que produit
 * fréquemment la reconnaissance vocale française. Le reste de la phrase est
 * rendu à l'appelant pour être envoyé tel quel.
 */
const WAKE_PATTERN = /^\s*(?:(?:hey|hé|salut|ok|okay)[\s,]+)?(?:kwes+|kw[ée]ss?|kou[eè]s+)\b[\s,.:!?…-]*(.*)$/is;

export function matchWakeWord(text: string): { matched: boolean; rest: string } {
  const normalized = (text ?? '').normalize('NFC').trim();
  if (!normalized) return { matched: false, rest: '' };
  const match = WAKE_PATTERN.exec(normalized);
  if (!match) return { matched: false, rest: normalized };
  return { matched: true, rest: (match[1] ?? '').trim() };
}

/* ------------------------------------------------------------------ */
/* Détection de silence et découpage en phrases                        */
/* ------------------------------------------------------------------ */

export const SILENCE_MS = 1200;
const MIN_UTTERANCE_CHARS = 2;

/** Le silence est écoulé et la phrase mérite d'être envoyée. */
export function shouldSubmitOnSilence(pending: string, elapsedMs: number, threshold = SILENCE_MS): boolean {
  return elapsedMs >= threshold && pending.trim().length >= MIN_UTTERANCE_CHARS;
}

const TERMINATORS = '.!?…';
const CLOSERS = '»"’\')';
/** Abréviations courantes : un point après elles ne termine pas la phrase. */
const ABBREVIATIONS = new Set([
  'm', 'mm', 'mme', 'mlle', 'mmes', 'dr', 'pr', 'st', 'ste', 'etc', 'cf',
  'env', 'art', 'p', 'pp', 'fig', 'réf', 'ref', 'av', 'bd', 'ex', 'n', 'nos', 'vol', 'cf',
]);

function isAbbreviationPoint(text: string, terminatorIndex: number): boolean {
  if (text[terminatorIndex] !== '.') return false;
  let start = terminatorIndex;
  while (start > 0 && /[A-Za-zÀ-ÿ]/.test(text[start - 1] ?? '')) start -= 1;
  const word = text.slice(start, terminatorIndex);
  if (!word) return false;
  if (word.length === 1 && word === word.toUpperCase()) return true; // initiale : « M. Dupont »
  return ABBREVIATIONS.has(word.toLowerCase());
}

/**
 * Extrait les phrases complètes d'un tampon de streaming et rend le reste.
 * Une phrase = terminateur suivi d'une espace/fin de tampon, hors nombres
 * décimaux (« 1.5 ») et abréviations (« M. Dupont »).
 */
export function splitSentences(buffer: string): { sentences: string[]; rest: string } {
  const sentences: string[] = [];
  let start = 0;
  let index = 0;

  while (index < buffer.length) {
    const char = buffer[index];
    const isNewline = char === '\n';
    if (!TERMINATORS.includes(char) && !isNewline) {
      index += 1;
      continue;
    }
    if (!isNewline && isAbbreviationPoint(buffer, index)) {
      index += 1;
      continue;
    }
    // Regroupe « ?!… » et les guillemets fermants
    let end = index + 1;
    while (end < buffer.length && (TERMINATORS.includes(buffer[end]) || CLOSERS.includes(buffer[end]))) {
      end += 1;
    }
    const next = buffer[end];
    if (!isNewline && next !== undefined && !/\s/.test(next)) {
      index = end;
      continue;
    }
    const candidate = buffer.slice(start, end).trim();
    if (candidate) sentences.push(candidate);
    start = end;
    index = end;
  }

  return { sentences, rest: buffer.slice(start) };
}

/** État d'Orb correspondant — strictement dérivé de la phase réelle. */
export function orbStateFor(phase: VoicePhase): 'idle' | 'listening' | 'thinking' | 'speaking' {
  return phase;
}

/**
 * Nettoie le markdown avant synthèse : le modèle répond en markdown et
 * le moteur vocal lirait « astérisque astérisque ». On garde le texte, pas la mise en forme.
 */
export function stripMarkdownForSpeech(text: string): string {
  return (text ?? '')
    .replace(/```[a-zA-Z]*\s*/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s{0,3}[-*+]\s+/gm, '')
    .replace(/^\s{0,3}\d+[.)]\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)([^*_\n]+)\1/g, '$2')
    .replace(/~~(.*?)~~/g, '$1')
    // Résidus de formatage (astérisques orphelins) : jamais du contenu parlé.
    .replace(/\*+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ------------------------------------------------------------------ */
/* Premier contact : la découverte                                     */
/* ------------------------------------------------------------------ */

/**
 * Le tout premier message de Kwes, joué dès l'ouverture du mode vocal.
 * Une phrase de présentation, puis UNE question — jamais deux.
 */
export const FIRST_CONTACT_MESSAGE =
  "Bonjour, moi c'est Kwes — votre assistant personnel. " +
  'Pour commencer, qu’est-ce que vous faites dans la vie ?';

/** Clé locale : la découverte ne se rejoue pas à chaque ouverture. */
export const FIRST_CONTACT_KEY = 'kwes.voice.firstContact';

/** Stockage minimal : `localStorage` en vrai, un objet factice en test. */
export interface KeyValueStore {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

export function defaultStore(): KeyValueStore | null {
  try {
    if (typeof localStorage === 'undefined' || !localStorage) return null;
    return localStorage;
  } catch {
    return null;
  }
}

/** Kwes s'est-il déjà présenté sur cet appareil ? */
export function hasMetKwes(store: KeyValueStore | null = defaultStore()): boolean {
  if (!store) return false;
  try {
    return store.getItem(FIRST_CONTACT_KEY) === '1';
  } catch {
    return false;
  }
}

/** Marque la présentation comme faite ; rend `false` si le stockage refuse. */
export function markKwesMet(store: KeyValueStore | null = defaultStore()): boolean {
  if (!store) return false;
  try {
    store.setItem(FIRST_CONTACT_KEY, '1');
    return true;
  } catch {
    return false;
  }
}

/**
 * Faut-il prendre la parole en premier ? Uniquement à la première session
 * vocale : ni en veille (l'utilisateur a demandé le silence), ni si le mode est
 * déjà actif.
 */
export function shouldOpenDiscovery(input: {
  metBefore: boolean;
  standby: boolean;
  active: boolean;
}): boolean {
  return !input.metBefore && !input.standby && !input.active;
}

/* ------------------------------------------------------------------ */
/* Barge-in : distinguer la voix de l'utilisateur de l'écho du haut-parleur */
/* ------------------------------------------------------------------ */

function speechWords(text: string): string[] {
  return (text ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .split(' ')
    .filter(Boolean);
}

/**
 * La phrase reconnue ressemble-t-elle à ce que Kwes est en train de dire ?
 * Si oui, c'est le haut-parleur qui revient dans le micro : couper l'audio
 * serait une auto-interruption, pas un barge-in.
 */
export function looksLikeEcho(heard: string, spoken: string): boolean {
  const heardWords = speechWords(heard);
  if (heardWords.length === 0) return false;
  const spokenWords = new Set(speechWords(spoken));
  if (spokenWords.size === 0) return false;
  let found = 0;
  for (const word of heardWords) {
    if (spokenWords.has(word)) found += 1;
  }
  return found / heardWords.length >= 0.6;
}

/** Libellés accessibles (aria-live discret). */
export function voiceStatusLabel(state: VoiceSessionState): string {
  if (!state.active) return 'Mode vocal désactivé.';
  switch (state.phase) {
    case 'listening':
      // La transcription est affichée à part : on ne la répète pas ici.
      return state.armed
        ? 'Micro actif, à vous.'
        : 'En veille : dites « Kwes » pour m’activer.';
    case 'thinking':
      return 'Kwes réfléchit.';
    case 'speaking':
      return 'Kwes répond à voix haute. Parlez pour interrompre.';
    default:
      return 'Mode vocal prêt.';
  }
}

/**
 * Annonce aria-live : courte et stable. On n'y met jamais la transcription
 * (elle change à chaque mot et saturerait un lecteur d'écran).
 */
export function voiceAnnouncement(state: VoiceSessionState): string {
  if (!state.active) return '';
  switch (state.phase) {
    case 'listening':
      return state.armed ? 'Kwes écoute.' : 'En veille. Dites Kwes pour m’activer.';
    case 'thinking':
      return 'Kwes réfléchit.';
    case 'speaking':
      return 'Kwes répond à voix haute. Parlez pour interrompre.';
    default:
      return 'Mode vocal coupé.';
  }
}
