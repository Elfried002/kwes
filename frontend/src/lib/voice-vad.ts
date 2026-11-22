/**
 * Détection de parole locale (VAD) qui pilote le tour de parole de Gemini Live.
 *
 * La session Live est configurée avec `automatic_activity_detection` désactivée :
 * c'est le navigateur qui envoie `activity_start` / `activity_end`, et ce
 * découpage est la cause première des trois défauts constatés à l'usage —
 * phrases répétées, réponse coupée, latence avant la réponse :
 *
 * - l'ancien seuil ouvrait un tour sur **une seule** trame de 64 ms. La queue de
 *   la phrase, juste après `activity_end`, rouvrait donc un micro-tour ; le
 *   modèle le transcrivait en n'importe quoi (« ¿Qué? ») ou répondait une
 *   deuxième fois la même chose ;
 * - une hésitation de 400 ms fermait le tour au milieu de la phrase : deux
 *   réponses pour une question ;
 * - le micro continuait à écouter pendant la réponse : l'écho du haut-parleur
 *   déclenchait une interruption, la réponse était coupée puis relancée.
 *
 * Ce module est pur (aucun DOM, aucun audio) : chaque décision se teste.
 */

export interface VadOptions {
  /** Niveau RMS qui ouvre une prise de parole. */
  startRms: number;
  /** Trames consécutives au-dessus du seuil avant d'ouvrir le tour. */
  startFrames: number;
  /** Niveau RMS exigé pour interrompre une réponse en cours (anti-écho). */
  bargeInRms: number;
  /** Trames consécutives exigées pour interrompre (≈ 250 ms). */
  bargeInFrames: number;
  /** Sous ce niveau, on compte du silence. */
  silenceRms: number;
  /** Silence cumulé avant de clore le tour (hystérésis). */
  silenceMs: number;
  /** Délai après une fin de tour pendant lequel rien ne peut rouvrir un tour. */
  cooldownMs: number;
  /** Tramses conservées pour ne pas couper l'attaque du premier mot. */
  prerollFrames: number;
}

export const VAD_DEFAULTS: VadOptions = {
  startRms: 0.02,
  // 3 × 64 ms : un clic, une toux ou la queue d'une phrase ne suffisent plus.
  startFrames: 3,
  // L'écho du haut-parleur est plus faible qu'une vraie voix proche du micro.
  bargeInRms: 0.06,
  bargeInFrames: 4,
  silenceRms: 0.008,
  // 450 ms : couvre une hésitation (« euh… ») sans ajouter 200 ms perçues.
  silenceMs: 450,
  // 300 ms : le temps que la queue de la phrase retombe, jamais un vrai tour.
  cooldownMs: 300,
  prerollFrames: 8,
};

export interface VadState {
  speaking: boolean;
  /** Trames consécutives au-dessus du seuil d'ouverture. */
  loud: number;
  /** Silence cumulé depuis la dernière trame de voix. */
  silenceMs: number;
  /** Instant (ms) avant lequel aucun tour ne peut s'ouvrir. */
  cooldownUntil: number;
  /** Trames gardées en réserve (base64) pour l'attaque du premier mot. */
  preroll: string[];
}

export interface VadFrame {
  rms: number;
  frameMs: number;
  nowMs: number;
  /** Vrai quand l'audio de l'assistant est en train d'être joué. */
  playing: boolean;
  payload: string;
}

export interface VadDecision {
  action: 'start' | 'end' | null;
  /** Envoyer la trame courante comme audio (hors ouverture, qui flushe). */
  send: boolean;
  /** Trames à envoyer juste après `activity_start`, dans l'ordre. */
  flush: string[];
  /** Le tour a été ouvert pendant que l'assistant parlait : c'est un barge-in. */
  bargeIn: boolean;
}

export function createVadState(): VadState {
  return { speaking: false, loud: 0, silenceMs: 0, cooldownUntil: 0, preroll: [] };
}

const IDLE: VadDecision = { action: null, send: false, flush: [], bargeIn: false };

export function pushVadFrame(
  state: VadState,
  frame: VadFrame,
  options: VadOptions = VAD_DEFAULTS,
): VadDecision {
  if (!state.speaking) {
    const threshold = frame.playing ? options.bargeInRms : options.startRms;
    const needed = frame.playing ? options.bargeInFrames : options.startFrames;
    if (frame.nowMs < state.cooldownUntil) {
      state.loud = 0;
    } else if (frame.rms >= threshold) {
      state.loud += 1;
    } else {
      state.loud = 0;
    }
    state.preroll.push(frame.payload);
    while (state.preroll.length > options.prerollFrames) state.preroll.shift();

    if (state.loud >= needed) {
      const flush = state.preroll.slice();
      state.preroll = [];
      state.speaking = true;
      state.loud = 0;
      state.silenceMs = 0;
      return { action: 'start', send: false, flush, bargeIn: frame.playing };
    }
    return IDLE;
  }

  state.silenceMs = frame.rms < options.silenceRms ? state.silenceMs + frame.frameMs : 0;
  if (state.silenceMs >= options.silenceMs) {
    state.speaking = false;
    state.silenceMs = 0;
    state.cooldownUntil = frame.nowMs + options.cooldownMs;
    return { action: 'end', send: true, flush: [], bargeIn: false };
  }
  return { action: null, send: true, flush: [], bargeIn: false };
}
