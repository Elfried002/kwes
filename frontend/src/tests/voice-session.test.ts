import { describe, expect, it } from 'vitest';
import {
  SILENCE_MS,
  initialVoiceState,
  matchWakeWord,
  orbStateFor,
  reduceVoice,
  shouldCutAudio,
  shouldSubmitOnSilence,
  splitSentences,
  stripMarkdownForSpeech,
  voiceAnnouncement,
  voiceStatusLabel,
  type VoiceEvent,
  type VoiceSessionState,
} from '../lib/voice-session';

function run(events: VoiceEvent[], from: VoiceSessionState = initialVoiceState): VoiceSessionState {
  return events.reduce(reduceVoice, from);
}

describe('machine à états vocale', () => {
  it('enchaîne idle → listening → thinking → speaking → idle', () => {
    let state = reduceVoice(initialVoiceState, { type: 'ACTIVATE' });
    expect(state.phase).toBe('listening');
    expect(state.active).toBe(true);

    state = reduceVoice(state, { type: 'MIC_READY' });
    expect(state.phase).toBe('listening');

    state = reduceVoice(state, { type: 'UTTERANCE', text: 'Quel temps fait-il ?' });
    expect(state.phase).toBe('thinking');
    expect(state.streaming).toBe(true);

    state = reduceVoice(state, { type: 'DELTA', text: 'Il fait beau. ' });
    expect(state.answer).toBe('Il fait beau. ');
    expect(state.phase).toBe('thinking');

    state = reduceVoice(state, { type: 'AUDIO_QUEUED' });
    state = reduceVoice(state, { type: 'AUDIO_PLAYING' });
    expect(state.phase).toBe('speaking');

    state = reduceVoice(state, { type: 'STREAM_DONE' });
    // L'audio n'est pas terminé : on ne quitte pas `speaking`.
    expect(state.phase).toBe('speaking');
    expect(state.streaming).toBe(false);

    state = reduceVoice(state, { type: 'AUDIO_ENDED' });
    expect(state.phase).toBe('listening');
    expect(state.queued).toBe(0);

    state = reduceVoice(state, { type: 'DEACTIVATE' });
    expect(state.phase).toBe('idle');
    expect(state.active).toBe(false);
  });

  it('ne quitte pas speaking tant que des phrases restent à lire', () => {
    let state = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Raconte' },
      { type: 'AUDIO_QUEUED' },
      { type: 'AUDIO_QUEUED' },
      { type: 'AUDIO_PLAYING' },
      { type: 'STREAM_DONE' },
      { type: 'AUDIO_ENDED' },
    ]);
    expect(state.phase).toBe('speaking');
    expect(state.queued).toBe(1);

    state = reduceVoice(state, { type: 'AUDIO_ENDED' });
    expect(state.phase).toBe('listening');
    expect(state.queued).toBe(0);
  });

  it('revient en listening (et non thinking) quand la réponse finit sans audio', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Bonjour' },
      { type: 'DELTA', text: 'Salut.' },
      { type: 'STREAM_DONE' },
    ]);
    expect(state.phase).toBe('listening');
    expect(state.streaming).toBe(false);
  });

  it('revient en idle si le mode a été coupé pendant le tour', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Bonjour' },
      { type: 'DELTA', text: 'Salut.' },
      { type: 'DEACTIVATE' },
      { type: 'STREAM_DONE' },
    ]);
    expect(state.phase).toBe('idle');
    expect(state.active).toBe(false);
  });

  it('coupe l’audio et repasse en écoute sur barge-in', () => {
    const speaking = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Raconte une histoire' },
      { type: 'DELTA', text: 'Il était une fois. ' },
      { type: 'AUDIO_QUEUED' },
      { type: 'AUDIO_QUEUED' },
      { type: 'AUDIO_PLAYING' },
    ]);
    expect(speaking.phase).toBe('speaking');
    expect(shouldCutAudio(speaking)).toBe(true);

    const interrupted = reduceVoice(speaking, { type: 'BARGE_IN' });
    expect(interrupted.phase).toBe('listening');
    expect(interrupted.queued).toBe(0);
    expect(interrupted.streaming).toBe(false);
    expect(interrupted.answer).toBe('');
    expect(shouldCutAudio(interrupted)).toBe(false);
  });

  it('ignore une phrase reçue hors écoute (pas de double envoi)', () => {
    const thinking = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Premier' },
    ]);
    const after = reduceVoice(thinking, { type: 'UTTERANCE', text: 'Deuxième' });
    expect(after).toBe(thinking);
  });

  it('n’accepte aucune parole quand le mode est inactif', () => {
    expect(reduceVoice(initialVoiceState, { type: 'UTTERANCE', text: 'test' }).phase).toBe('idle');
    expect(reduceVoice(initialVoiceState, { type: 'INTERIM', text: 'test' }).pending).toBe('');
    expect(reduceVoice(initialVoiceState, { type: 'BARGE_IN' }).phase).toBe('idle');
  });

  it('signale une erreur de flux sans prétendre avoir répondu', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Bonjour' },
      { type: 'DELTA', text: 'Début' },
      { type: 'STREAM_ERROR', message: 'Service indisponible.' },
    ]);
    expect(state.phase).toBe('listening');
    expect(state.error).toBe('Service indisponible.');
    expect(state.answer).toBe('');
    expect(state.streaming).toBe(false);
  });

  it('désactive le micro sur échec matériel', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'MIC_FAILED', message: 'Accès au microphone refusé.' },
    ]);
    expect(state.active).toBe(false);
    expect(state.phase).toBe('idle');
    expect(state.error).toBe('Accès au microphone refusé.');
  });

  it('arme l’écoute uniquement sur le mot d’activation en veille', () => {
    let state = run([{ type: 'ACTIVATE' }, { type: 'STANDBY', enabled: true }]);
    expect(state.standby).toBe(true);
    expect(state.armed).toBe(false);
    expect(voiceStatusLabel(state)).toContain('Kwes');

    state = reduceVoice(state, { type: 'WAKE_WORD' });
    expect(state.armed).toBe(true);
    expect(state.phase).toBe('listening');
  });

  it('se désarme à la fin de chaque échange en veille', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'STANDBY', enabled: true },
      { type: 'WAKE_WORD' },
      { type: 'UTTERANCE', text: 'Quelle heure est-il ?' },
      { type: 'AUDIO_QUEUED' },
      { type: 'AUDIO_PLAYING' },
      { type: 'STREAM_DONE' },
      { type: 'AUDIO_ENDED' },
    ]);
    expect(state.phase).toBe('listening');
    expect(state.armed).toBe(false);
    expect(voiceStatusLabel(state)).toContain('veille');
  });

  it('reste armé en conversation continue (veille désactivée)', () => {
    const state = run([
      { type: 'ACTIVATE' },
      { type: 'UTTERANCE', text: 'Bonjour' },
      { type: 'STREAM_DONE' },
    ]);
    expect(state.phase).toBe('listening');
    expect(state.armed).toBe(true);
  });
});

describe('détection de silence', () => {
  it('envoie après 1,2 s de silence avec du texte', () => {
    expect(shouldSubmitOnSilence('Quel temps fait-il', SILENCE_MS)).toBe(true);
    expect(shouldSubmitOnSilence('Quel temps fait-il', SILENCE_MS - 1)).toBe(false);
  });

  it('n’envoie jamais un silence vide', () => {
    expect(shouldSubmitOnSilence('', SILENCE_MS * 3)).toBe(false);
    expect(shouldSubmitOnSilence('a', SILENCE_MS * 3)).toBe(false);
    expect(shouldSubmitOnSilence('   ', SILENCE_MS * 3)).toBe(false);
  });
});

describe('mot d’activation', () => {
  it('reconnaît « Kwes » et « Hey Kwes »', () => {
    expect(matchWakeWord('Kwes')).toEqual({ matched: true, rest: '' });
    expect(matchWakeWord('hey Kwes')).toEqual({ matched: true, rest: '' });
    expect(matchWakeWord('Hey Kwes, quelle heure est-il ?')).toEqual({
      matched: true,
      rest: 'quelle heure est-il ?',
    });
    expect(matchWakeWord('ok kwes ouvre mes tâches')).toEqual({
      matched: true,
      rest: 'ouvre mes tâches',
    });
  });

  it('tolère les graphies fréquentes de la reconnaissance vocale', () => {
    expect(matchWakeWord('Kwess ?').matched).toBe(true);
    expect(matchWakeWord('Kouès').matched).toBe(true);
    expect(matchWakeWord('quest-ce que tu fais').matched).toBe(false);
  });

  it('ne confond pas une phrase ordinaire avec le mot d’activation', () => {
    expect(matchWakeWord('Quelle heure est-il ?')).toEqual({
      matched: false,
      rest: 'Quelle heure est-il ?',
    });
    expect(matchWakeWord('').matched).toBe(false);
  });
});

describe('découpage en phrases pour la synthèse', () => {
  it('extrait les phrases complètes et conserve le reste', () => {
    const { sentences, rest } = splitSentences('Bonjour. Comment allez-vous ? Je vais bien');
    expect(sentences).toEqual(['Bonjour.', 'Comment allez-vous ?']);
    expect(rest).toBe(' Je vais bien');
  });

  it('ne coupe pas un nombre décimal ni une abréviation', () => {
    expect(splitSentences('Il reste 1.5 point').sentences).toEqual([]);
    expect(splitSentences('M. Dupont arrive.').sentences).toEqual(['M. Dupont arrive.']);
  });

  it('gère les points de suspension et les guillemets', () => {
    expect(splitSentences('Attendez… c’est fait !').sentences).toEqual(['Attendez…', ' c’est fait !'].map((s) => s.trim()));
    expect(splitSentences('Il dit « oui. » Puis il part.').sentences).toHaveLength(2);
  });

  it('traite le retour à la ligne comme une frontière', () => {
    const { sentences, rest } = splitSentences('Première ligne\nDeuxième en cours');
    expect(sentences).toEqual(['Première ligne']);
    expect(rest).toBe('Deuxième en cours');
  });

  it('assemble correctement des deltas successifs', () => {
    let buffer = '';
    const spoken: string[] = [];
    for (const delta of ['Bonjour, ', 'je suis Kwes. ', 'Comment ', 'puis-je aider ?']) {
      buffer += delta;
      const { sentences, rest } = splitSentences(buffer);
      buffer = rest;
      spoken.push(...sentences);
    }
    expect(spoken).toEqual(['Bonjour, je suis Kwes.', 'Comment puis-je aider ?']);
    expect(buffer.trim()).toBe('');
  });
});

describe('mapping Orb / libellés', () => {
  it('dérive strictement les états d’Orb de la phase réelle', () => {
    expect(orbStateFor('idle')).toBe('idle');
    expect(orbStateFor('listening')).toBe('listening');
    expect(orbStateFor('thinking')).toBe('thinking');
    expect(orbStateFor('speaking')).toBe('speaking');
  });

  it('donne un libellé explicite pour chaque phase', () => {
    expect(voiceStatusLabel(initialVoiceState)).toContain('désactivé');
    expect(
      voiceStatusLabel({ ...initialVoiceState, active: true, armed: true, phase: 'listening' }),
    ).toContain('Micro actif');
    expect(
      voiceStatusLabel({ ...initialVoiceState, active: true, phase: 'speaking' }),
    ).toContain('interrompre');
  });
});

describe('annonces aria-live', () => {
  it('annonce l’état sans jamais répéter la transcription', () => {
    const listening = {
      ...initialVoiceState,
      active: true,
      armed: true,
      phase: 'listening' as const,
      pending: 'une phrase très longue en cours de dictée',
    };
    expect(voiceAnnouncement(listening)).toBe('Kwes écoute.');
    expect(voiceAnnouncement(listening)).not.toContain('dictée');
    expect(voiceAnnouncement({ ...listening, armed: false })).toContain('veille');
    expect(voiceAnnouncement({ ...listening, phase: 'thinking' })).toBe('Kwes réfléchit.');
    expect(voiceAnnouncement({ ...listening, phase: 'speaking' })).toContain('interrompre');
    expect(voiceAnnouncement(initialVoiceState)).toBe('');
  });
});

describe('nettoyage avant synthèse', () => {
  it('retire les marqueurs markdown que la voix lirait', () => {
    expect(stripMarkdownForSpeech('La capitale est **Porto-Novo**.')).toBe(
      'La capitale est Porto-Novo.',
    );
    expect(stripMarkdownForSpeech('## Titre\n- point un\n- point deux')).toBe(
      'Titre point un point deux',
    );
  });

  it('remplace un lien par son libellé et garde le code inline', () => {
    expect(stripMarkdownForSpeech('Voir [la doc](https://exemple.com/a) pour `npm run dev`.')).toBe(
      'Voir la doc pour npm run dev.',
    );
  });

  it('ne laisse pas de texte vide sur du pur formatage', () => {
    expect(stripMarkdownForSpeech('***')).toBe('');
    expect(stripMarkdownForSpeech('   ')).toBe('');
  });

  it('préserve les apostrophes et les accents', () => {
    expect(stripMarkdownForSpeech("C'est l'été — 18 °C.")).toBe("C'est l'été — 18 °C.");
  });
});
