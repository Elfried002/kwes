import { describe, expect, it } from 'vitest';
import {
  estimateSpeechMs,
  playbackFraction,
  revealCaption,
  speechEnvelope,
} from '../lib/kwes-speech';

const PHRASE = 'Votre journée est légère, deux rendez-vous sans conflit.';

describe('sous-titre au rythme de la parole', () => {
  it('affiche le premier mot dès le démarrage de la voix', () => {
    expect(revealCaption(PHRASE, 0)).toBe('Votre');
  });

  it('n’affiche jamais un mot coupé', () => {
    for (const fraction of [0.05, 0.13, 0.27, 0.41, 0.58, 0.73, 0.86, 0.97]) {
      const caption = revealCaption(PHRASE, fraction);
      expect(caption.endsWith(' ')).toBe(false);
      expect(PHRASE.startsWith(caption)).toBe(true);
      // Le caractère suivant est toujours une frontière de mot.
      expect([' ', undefined]).toContain(PHRASE.charAt(caption.length) || undefined);
    }
  });

  it('affiche la phrase entière quand la lecture est terminée', () => {
    expect(revealCaption(PHRASE, 1)).toBe(PHRASE);
    expect(revealCaption(PHRASE, 1.4)).toBe(PHRASE);
  });

  it('progresse avec la fraction, sans jamais reculer', () => {
    const lengths = [0, 0.2, 0.4, 0.6, 0.8, 1].map(
      (fraction) => revealCaption(PHRASE, fraction).length,
    );
    for (let index = 1; index < lengths.length; index += 1) {
      expect(lengths[index] as number).toBeGreaterThanOrEqual(lengths[index - 1] as number);
    }
  });

  it('gère une phrase d’un seul mot et une phrase vide', () => {
    // Un mot seul n'a pas de frontière : il s'affiche d'un coup.
    expect(revealCaption('Bonjour', 0.5)).toBe('Bonjour');
    expect(revealCaption('Bonjour', 1)).toBe('Bonjour');
    expect(revealCaption('', 0.5)).toBe('');
    expect(revealCaption('   ', 0.5)).toBe('');
  });

  it('traite une fraction absurde comme un démarrage', () => {
    expect(revealCaption(PHRASE, Number.NaN)).toBe('Votre');
    expect(revealCaption(PHRASE, -3)).toBe('Votre');
  });
});

describe('part de lecture réelle', () => {
  it('suit la position de l’audio', () => {
    expect(playbackFraction(0, 4)).toBe(0);
    expect(playbackFraction(2, 4)).toBe(0.5);
    expect(playbackFraction(4, 4)).toBe(1);
    expect(playbackFraction(9, 4)).toBe(1);
  });

  it('ne prétend rien quand la durée est inconnue', () => {
    expect(playbackFraction(1.2, Number.NaN)).toBe(0);
    expect(playbackFraction(1.2, 0)).toBe(0);
    expect(playbackFraction(Number.POSITIVE_INFINITY, 3)).toBe(0);
  });
});

describe('voix de l’appareil', () => {
  it('estime une durée bornée, croissante avec la longueur', () => {
    expect(estimateSpeechMs('')).toBe(700);
    expect(estimateSpeechMs('Un instant.')).toBeLessThan(estimateSpeechMs(PHRASE));
    expect(estimateSpeechMs(PHRASE)).toBeGreaterThanOrEqual(700);
  });

  it('anime la bouche dans une plage stable, sans valeur extrême', () => {
    const samples = Array.from({ length: 120 }, (_, index) => speechEnvelope(index / 12));
    for (const value of samples) {
      expect(value).toBeGreaterThanOrEqual(0.1);
      expect(value).toBeLessThanOrEqual(0.72);
    }
    // La cadence bouge : la bouche ne reste pas figée pendant la parole.
    expect(Math.max(...samples) - Math.min(...samples)).toBeGreaterThan(0.15);
  });

  it('reste définie pour une horloge absurde', () => {
    expect(Number.isFinite(speechEnvelope(Number.NaN))).toBe(true);
  });
});
