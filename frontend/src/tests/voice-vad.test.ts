import { describe, expect, it } from 'vitest';
import {
  createVadState,
  pushVadFrame,
  VAD_DEFAULTS,
  type VadDecision,
  type VadState,
} from '../lib/voice-vad';

const FRAME_MS = 64;

interface Segment {
  frames: number;
  rms: number;
  playing?: boolean;
}

interface Env {
  state: VadState;
  /** Joue une enveloppe (parole / silence) ; l'horloge continue d'un appel à l'autre. */
  play: (segments: Segment[]) => VadDecision[];
  now: () => number;
}

function makeEnv(): Env {
  const state = createVadState();
  let clock = 0;
  return {
    state,
    now: () => clock,
    play(segments) {
      const decisions: VadDecision[] = [];
      for (const segment of segments) {
        for (let index = 0; index < segment.frames; index += 1) {
          decisions.push(
            pushVadFrame(state, {
              rms: segment.rms,
              frameMs: FRAME_MS,
              nowMs: clock,
              playing: segment.playing ?? false,
              payload: `trame-${clock}`,
            }),
          );
          clock += FRAME_MS;
        }
      }
      return decisions;
    },
  };
}

const silence = (frames: number, playing = false): Segment => ({ frames, rms: 0, playing });
const speech = (frames: number, rms = 0.06, playing = false): Segment => ({ frames, rms, playing });
const count = (decisions: VadDecision[], action: 'start' | 'end') =>
  decisions.filter((entry) => entry.action === action).length;

describe('VAD : un tour = une question', () => {
  it('une hésitation de 420 ms ne coupe pas le tour en deux', () => {
    const env = makeEnv();
    const decisions = env.play([
      silence(8),
      speech(40),
      // 6 × 64 = 384 ms de silence : une hésitation, pas une fin de tour.
      silence(6),
      speech(30),
      silence(12),
    ]);
    expect(count(decisions, 'start')).toBe(1);
    expect(count(decisions, 'end')).toBe(1);
  });

  it('le seuil de silence de fin de tour reste sous 500 ms', () => {
    expect(VAD_DEFAULTS.silenceMs).toBeGreaterThanOrEqual(400);
    expect(VAD_DEFAULTS.silenceMs).toBeLessThanOrEqual(500);
  });

  it('un silence franc ferme bien le tour', () => {
    const env = makeEnv();
    const ends = env
      .play([silence(4), speech(30), silence(10)])
      .filter((entry) => entry.action === 'end');
    expect(ends).toHaveLength(1);
    // La trame qui déclenche la fin part quand même au serveur.
    expect(ends[0].send).toBe(true);
  });
});

describe('VAD : plus de micro-tours ni de répétitions', () => {
  it('la queue de la phrase ne rouvre pas un tour juste après la fin', () => {
    const env = makeEnv();
    env.play([silence(4), speech(30), silence(10)]);
    // Deux trames fortes dans les 100 ms qui suivent : ancien comportement =
    // un nouveau tour (donc une deuxième réponse), d'où les répétitions.
    expect(count(env.play([speech(2, 0.09)]), 'start')).toBe(0);
  });

  it('un bruit court (128 ms) n’ouvre pas de tour', () => {
    const env = makeEnv();
    expect(count(env.play([silence(4), speech(2, 0.08), silence(10)]), 'start')).toBe(0);
  });

  it('un clic isolé très fort n’ouvre pas de tour', () => {
    const env = makeEnv();
    expect(count(env.play([silence(4), speech(1, 0.4), silence(10)]), 'start')).toBe(0);
  });

  it('après le délai de garde, une vraie reprise ouvre un nouveau tour', () => {
    const env = makeEnv();
    env.play([silence(4), speech(30), silence(10)]);
    // 5 trames de silence (320 ms) dépassent la garde de 300 ms.
    expect(count(env.play([silence(5), speech(4, 0.06)]), 'start')).toBe(1);
  });
});

describe('VAD : l’écho du haut-parleur ne coupe plus la réponse', () => {
  it('un écho modéré pendant la lecture n’interrompt pas', () => {
    const env = makeEnv();
    expect(count(env.play([silence(4), speech(20, 0.03, true), silence(4)]), 'start')).toBe(0);
  });

  it('une voix forte et tenue pendant la lecture interrompt (barge-in)', () => {
    const env = makeEnv();
    const start = env.play([silence(4), speech(6, 0.09, true)]).find((entry) => entry.action === 'start');
    expect(start).toBeDefined();
    expect(start?.bargeIn).toBe(true);
  });

  it('le pré-roll rejoue les trames d’attaque, sans doublon', () => {
    const env = makeEnv();
    const start = env.play([silence(4), speech(4, 0.06)]).find((entry) => entry.action === 'start');
    expect(start).toBeDefined();
    // 4 trames de silence + les 3 trames nécessaires à la confirmation.
    expect(start?.flush.length).toBe(4 + 3);
    expect(new Set(start?.flush).size).toBe(start?.flush.length);
    expect(start?.send).toBe(false);
  });
});
