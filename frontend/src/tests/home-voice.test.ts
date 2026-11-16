import { describe, expect, it } from 'vitest';
import {
  canReadAnswer,
  homeAnnouncement,
  homeCaption,
  initialHomeVoice,
  reduceHomeVoice,
  type HomeVoiceEvent,
  type HomeVoiceState,
} from '../lib/home-voice';

function run(events: HomeVoiceEvent[], from: HomeVoiceState = initialHomeVoice): HomeVoiceState {
  return events.reduce(reduceHomeVoice, from);
}

/** Ce que l'accueil peut afficher : une phrase, jamais la réponse entière. */
function streamedTurn(): HomeVoiceState {
  return run([
    { type: 'SEND' },
    { type: 'DELTA', text: 'Votre journée est légère. ' },
    { type: 'SENTENCE', text: 'Votre journée est légère.' },
    { type: 'PLAYING', text: 'Votre journée est légère.' },
    { type: 'SPOKEN', text: 'Votre journée est légère.' },
    { type: 'DELTA', text: 'Deux rendez-vous, aucun conflit. ' },
    { type: 'SENTENCE', text: 'Deux rendez-vous, aucun conflit.' },
  ]);
}

describe('accueil — Kwes répond à voix haute', () => {
  it('envoie puis réfléchit sans jamais afficher la réponse en bloc', () => {
    const state = run([{ type: 'SEND' }, { type: 'DELTA', text: 'Bonjour, voici votre journée.' }]);
    expect(state.phase).toBe('thinking');
    expect(state.streaming).toBe(true);
    // Le texte reçu existe dans l'état (pour « Lire la réponse »), mais rien
    // n'est affiché tant qu'une phrase n'est pas réellement prononcée.
    expect(state.answer).toContain('voici votre journée');
    expect(homeCaption(state)).toBe('');
  });

  it('passe en speaking au démarrage réel de la lecture, pas avant', () => {
    let state = run([{ type: 'SEND' }, { type: 'SENTENCE', text: 'Un instant.' }]);
    expect(state.phase).toBe('thinking');
    expect(homeCaption(state)).toBe('');

    state = reduceHomeVoice(state, { type: 'PLAYING', text: 'Un instant.' });
    expect(state.phase).toBe('speaking');
    expect(state.sentence).toBe('Un instant.');
    // La voix démarre : le premier mot est déjà affiché, le reste suit.
    expect(homeCaption(state)).toBe('Un');
  });

  it('révèle le sous-titre au rythme de la parole, sur des mots entiers', () => {
    let state = run([{ type: 'SEND' }, { type: 'SENTENCE', text: 'Votre journée est légère.' }]);
    state = reduceHomeVoice(state, { type: 'PLAYING', text: 'Votre journée est légère.' });

    state = reduceHomeVoice(state, { type: 'PROGRESS', text: 'Votre journée est légère.', fraction: 0.4 });
    const partial = homeCaption(state);
    expect(partial.length).toBeGreaterThan(0);
    expect(partial.length).toBeLessThan('Votre journée est légère.'.length);
    expect('Votre journée est légère.'.startsWith(partial)).toBe(true);
    // Jamais un mot coupé en deux.
    expect(partial.endsWith(' ')).toBe(false);
    // La révélation s'arrête sur une frontière de mot.
    expect('Votre journée est légère.'.charAt(partial.length)).toBe(' ');

    state = reduceHomeVoice(state, { type: 'PROGRESS', text: 'Votre journée est légère.', fraction: 1 });
    expect(homeCaption(state)).toBe('Votre journée est légère.');
  });

  it('ignore une progression qui appartient à une phrase déjà remplacée', () => {
    let state = run([
      { type: 'SEND' },
      { type: 'SENTENCE', text: 'Première phrase.' },
      { type: 'PLAYING', text: 'Première phrase.' },
      { type: 'SPOKEN', text: 'Première phrase.' },
      { type: 'SENTENCE', text: 'Deuxième phrase.' },
      { type: 'PLAYING', text: 'Deuxième phrase.' },
    ]);
    state = reduceHomeVoice(state, { type: 'PROGRESS', text: 'Première phrase.', fraction: 1 });
    // La progression périmée ne fait pas avancer la nouvelle phrase.
    expect(homeCaption(state)).toBe('Deuxième');
    expect(state.progress).toBe(0);
  });

  it('garde la parole ouverte entre deux phrases du même tour', () => {
    const state = run([
      { type: 'SEND' },
      { type: 'SENTENCE', text: 'D’abord ceci.' },
      { type: 'PLAYING', text: 'D’abord ceci.' },
      { type: 'SPOKEN', text: 'D’abord ceci.' },
    ]);
    // Le flux est encore ouvert : la bouche ne se referme pas entre deux phrases.
    expect(state.phase).toBe('speaking');
    expect(state.pending).toBe(0);
    expect(state.spoken).toBe(1);
  });

  it('revient au repos quand la dernière phrase est réellement terminée', () => {
    let state = streamedTurn();
    state = reduceHomeVoice(state, { type: 'DONE', conversationId: 'conv-1' });
    expect(state.streaming).toBe(false);
    // La 2e phrase est en file : la lecture n'est pas terminée.
    expect(state.phase).toBe('speaking');
    expect(state.pending).toBe(1);

    state = reduceHomeVoice(state, { type: 'PLAYING', text: 'Deux rendez-vous, aucun conflit.' });
    state = reduceHomeVoice(state, { type: 'SPOKEN', text: 'Deux rendez-vous, aucun conflit.' });
    expect(state.phase).toBe('idle');
    expect(state.spoken).toBe(2);
    expect(state.sentences).toBe(2);
    // Le sous-titre reste lisible après la fin de la parole.
    expect(homeCaption(state)).toBe('Deux rendez-vous, aucun conflit.');
  });

  it('interrompt net : audio coupé, sous-titre vidé, état au repos', () => {
    let state = streamedTurn();
    state = reduceHomeVoice(state, { type: 'PLAYING', text: 'Votre journée est légère.' });
    state = reduceHomeVoice(state, { type: 'STOP' });
    expect(state.phase).toBe('idle');
    expect(state.streaming).toBe(false);
    expect(state.sentence).toBe('');
    expect(homeCaption(state)).toBe('');
    expect(state.spoken).toBe(0);
    expect(state.pending).toBe(0);
  });

  it('un nouveau message efface la réponse précédente', () => {
    let state = streamedTurn();
    state = reduceHomeVoice(state, { type: 'PLAYING', text: 'Deux rendez-vous, aucun conflit.' });
    state = reduceHomeVoice(state, { type: 'CONVERSATION', id: 'conv-1' });
    state = reduceHomeVoice(state, { type: 'SEND' });
    expect(state.phase).toBe('thinking');
    expect(state.sentence).toBe('');
    expect(state.conversationId).toBeNull();
    expect(homeCaption(state)).toBe('');
  });

  it('affiche une erreur courte à la place du sous-titre', () => {
    const state = run([
      { type: 'SEND' },
      { type: 'ERROR', message: 'Le serveur n’a pas répondu dans le délai imparti.' },
    ]);
    expect(state.phase).toBe('error');
    expect(state.streaming).toBe(false);
    expect(homeCaption(state)).toBe('Le serveur n’a pas répondu dans le délai imparti.');
    expect(homeAnnouncement(state)).toContain('délai');
  });

  it('signale une réponse vide sans rien inventer', () => {
    const state = run([{ type: 'SEND' }, { type: 'DONE', conversationId: 'conv-2' }]);
    expect(state.phase).toBe('error');
    expect(state.error).toBe('Aucune réponse n’est revenue. Réessayez.');
  });

  it('n’ouvre « Lire la réponse » que lorsque la conversation existe', () => {
    let state = run([{ type: 'SEND' }, { type: 'DELTA', text: 'Texte.' }]);
    expect(canReadAnswer(state)).toBe(false);

    state = reduceHomeVoice(state, { type: 'CONVERSATION', id: 'conv-3' });
    expect(canReadAnswer(state)).toBe(false); // flux encore ouvert

    state = reduceHomeVoice(state, { type: 'DONE', conversationId: 'conv-3' });
    expect(canReadAnswer(state)).toBe(true);

    state = reduceHomeVoice(state, { type: 'SEND' });
    expect(canReadAnswer(state)).toBe(false);
  });

  it('annonce les états aux lecteurs d’écran sans la révélation mot à mot', () => {
    expect(homeAnnouncement(run([{ type: 'SEND' }]))).toBe('Kwes prépare sa réponse.');
    expect(
      homeAnnouncement(
        run([
          { type: 'SEND' },
          { type: 'SENTENCE', text: 'Voilà.' },
          { type: 'PLAYING', text: 'Voilà.' },
        ]),
      ),
    ).toBe('Kwes répond à voix haute.');
  });
});
