import { describe, expect, it } from 'vitest';
import {
  FIRST_CONTACT_KEY,
  FIRST_CONTACT_MESSAGE,
  hasMetKwes,
  initialVoiceState,
  looksLikeEcho,
  markKwesMet,
  reduceVoice,
  shouldOpenDiscovery,
  type KeyValueStore,
  type VoiceSessionState,
} from '../lib/voice-session';

/** Stockage mémoire : le vrai `localStorage` n'existe pas en environnement node. */
function memoryStore(seed: Record<string, string> = {}): KeyValueStore & { data: Record<string, string> } {
  const data: Record<string, string> = { ...seed };
  return {
    data,
    getItem: (key) => (key in data ? (data[key] as string) : null),
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

const speaking: VoiceSessionState = {
  ...initialVoiceState,
  active: true,
  armed: true,
  phase: 'speaking',
  streaming: true,
  queued: 2,
  answer: 'Une réponse en cours.',
};

describe('tour de parole : le micro ne doit jamais rendre la main à l’audio', () => {
  it('un redémarrage de la reconnaissance ne transforme pas « speaking » en écoute', () => {
    const next = reduceVoice(speaking, { type: 'MIC_READY' });
    expect(next.phase).toBe('speaking');
    expect(next.streaming).toBe(true);
    expect(next.queued).toBe(2);
  });

  it('un redémarrage pendant « thinking » ne relance pas l’écoute', () => {
    const thinking = reduceVoice(
      reduceVoice(initialVoiceState, { type: 'ACTIVATE' }),
      { type: 'UTTERANCE', text: 'Bonjour' },
    );
    expect(thinking.phase).toBe('thinking');
    const next = reduceVoice(thinking, { type: 'MIC_READY' });
    expect(next.phase).toBe('thinking');
    expect(next.streaming).toBe(true);
  });

  it('un redémarrage hors tour ramène bien en écoute (le cas normal reste couvert)', () => {
    const idleActive = { ...initialVoiceState, active: true, armed: true };
    expect(reduceVoice(idleActive, { type: 'MIC_READY' }).phase).toBe('listening');
  });

  it('« speaking » repasse en écoute et purge la file sur barge-in', () => {
    const interrupted = reduceVoice(speaking, { type: 'BARGE_IN' });
    expect(interrupted.phase).toBe('listening');
    expect(interrupted.queued).toBe(0);
    expect(interrupted.streaming).toBe(false);
  });
});

describe('écho du haut-parleur vs parole de l’utilisateur', () => {
  const spoken = 'Bonjour, moi c’est Kwes, votre assistant personnel.';

  it('reconnaît sa propre voix (même approximative) et ne se coupe pas', () => {
    expect(looksLikeEcho('bonjour moi c est kwes', spoken)).toBe(true);
    expect(looksLikeEcho('votre assistant personnel', spoken)).toBe(true);
    expect(looksLikeEcho('Kwes votre assistant', spoken)).toBe(true);
  });

  it('reconnaît une vraie prise de parole et coupe l’audio', () => {
    expect(looksLikeEcho('attends deux secondes', spoken)).toBe(false);
    expect(looksLikeEcho('stop', spoken)).toBe(false);
    expect(looksLikeEcho('je travaille dans la logistique', spoken)).toBe(false);
  });

  it('ne traite pas une transcription vide comme un écho', () => {
    expect(looksLikeEcho('', spoken)).toBe(false);
    expect(looksLikeEcho('   ', spoken)).toBe(false);
    expect(looksLikeEcho('bonjour', '')).toBe(false);
  });

  it('ignore la ponctuation, les accents et la casse', () => {
    expect(looksLikeEcho('BONJOUR, MOI C’EST KWES !', spoken)).toBe(true);
    expect(looksLikeEcho('bonjour moi c est kwés', spoken)).toBe(true);
  });
});

describe('premier contact', () => {
  it('le message de découverte se présente puis pose UNE seule question', () => {
    expect(FIRST_CONTACT_MESSAGE).toContain('Kwes');
    const questions = FIRST_CONTACT_MESSAGE.match(/\?/g) ?? [];
    expect(questions).toHaveLength(1);
    expect(FIRST_CONTACT_MESSAGE.trim().endsWith('?')).toBe(true);
    // Une phrase de présentation, courte : pas un discours.
    expect(FIRST_CONTACT_MESSAGE.length).toBeLessThan(160);
  });

  it('mémorise la présentation une seule fois', () => {
    const store = memoryStore();
    expect(hasMetKwes(store)).toBe(false);
    expect(markKwesMet(store)).toBe(true);
    expect(store.data[FIRST_CONTACT_KEY]).toBe('1');
    expect(hasMetKwes(store)).toBe(true);
  });

  it('ne prétend rien quand le stockage est indisponible', () => {
    expect(hasMetKwes(null)).toBe(false);
    expect(markKwesMet(null)).toBe(false);
    const broken: KeyValueStore = {
      getItem: () => {
        throw new Error('refusé');
      },
      setItem: () => {
        throw new Error('refusé');
      },
    };
    expect(hasMetKwes(broken)).toBe(false);
    expect(markKwesMet(broken)).toBe(false);
  });

  it('ne prend la parole en premier qu’à la première session, hors veille', () => {
    expect(shouldOpenDiscovery({ metBefore: false, standby: false, active: false })).toBe(true);
    expect(shouldOpenDiscovery({ metBefore: true, standby: false, active: false })).toBe(false);
    expect(shouldOpenDiscovery({ metBefore: false, standby: true, active: false })).toBe(false);
    expect(shouldOpenDiscovery({ metBefore: false, standby: false, active: true })).toBe(false);
  });
});
