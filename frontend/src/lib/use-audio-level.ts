/**
 * Niveau d'activité « réel » pour le dot vivant.
 *
 * - Quand Kwes parle : un AnalyserNode est branché sur le flux audio de la
 *   réponse (élément <audio> créé par le moteur vocal) et on mesure son RMS
 *   image par image. Le dot pulse donc avec le son, pas avec un minuteur.
 * - Quand l'utilisateur parle : la mesure vient de la reconnaissance vocale
 *   elle-même (`pulse` appelé à chaque mise à jour de transcription). On
 *   n'ouvre *pas* un second `getUserMedia` : sur Chrome Android, capturer le
 *   micro en même temps que `SpeechRecognition` casse la reconnaissance
 *   (crbug 41083534), donc la conversation. L'intensité reste indexée sur la
 *   parole réellement reconnue, jamais sur un aléatoire.
 *
 * Aucune donnée n'est conservée : le graphe audio vit uniquement pendant la
 * lecture et est démonté avec l'écran.
 */

import { useCallback, useEffect, useRef } from 'react';

export interface AudioLevel {
  /** Lu dans la boucle de rendu du dot : aucune re-render React. */
  levelRef: { current: number };
  /** Activité vocale de l'utilisateur (0..1), à appeler sur la transcription. */
  pulse: (strength: number) => void;
  /** Crée le contexte audio sur un geste utilisateur (politique autoplay). */
  prime: () => void;
}

type AudioContextConstructor = new () => AudioContext;

function getAudioContextConstructor(): AudioContextConstructor | null {
  if (typeof window === 'undefined') return null;
  const candidate = window as unknown as {
    AudioContext?: AudioContextConstructor;
    webkitAudioContext?: AudioContextConstructor;
  };
  return candidate.AudioContext ?? candidate.webkitAudioContext ?? null;
}

/** Le moteur vocal crée ses extraits en `data:audio/...` : on ne touche qu'à eux. */
const SPEECH_SRC_PREFIX = 'data:audio';

export function useAudioLevel(speaking: boolean): AudioLevel {
  const levelRef = useRef(0);
  const pulseRef = useRef(0);
  const contextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourcesRef = useRef<WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>>(new WeakMap());
  const frameRef = useRef(0);
  const tickRef = useRef<(now: number) => void>(() => undefined);
  const speakingRef = useRef(speaking);
  speakingRef.current = speaking;

  const prime = useCallback(() => {
    if (contextRef.current) {
      if (contextRef.current.state === 'suspended') void contextRef.current.resume();
      return;
    }
    const Constructor = getAudioContextConstructor();
    if (!Constructor) return;
    try {
      contextRef.current = new Constructor();
      void contextRef.current.resume().catch(() => {
        /* le contexte restera suspendu : le dot garde son mouvement propre */
      });
    } catch {
      contextRef.current = null;
    }
  }, []);

  /**
   * Branche l'analyseur sur un extrait de parole avant sa lecture. En cas de
   * refus ou d'échec, la lecture reste strictement inchangée (on ne branche
   * que si le contexte tourne déjà).
   */
  useEffect(() => {
    if (typeof window === 'undefined' || typeof HTMLMediaElement === 'undefined') return;
    const prototype = HTMLMediaElement.prototype;
    const original = prototype.play;
    if (typeof original !== 'function') return;

    const patched = function patchedPlay(this: HTMLMediaElement): Promise<void> {
      try {
        const context = contextRef.current;
        const isSpeech = typeof this.src === 'string' && this.src.startsWith(SPEECH_SRC_PREFIX);
        if (context && context.state === 'running' && isSpeech && !sourcesRef.current.has(this)) {
          const source = context.createMediaElementSource(this);
          const analyser = context.createAnalyser();
          analyser.fftSize = 1024;
          analyser.smoothingTimeConstant = 0.72;
          source.connect(analyser);
          // Le son doit continuer de sortir : analyseur → sortie.
          analyser.connect(context.destination);
          sourcesRef.current.set(this, source);
          analyserRef.current = analyser;
        }
      } catch {
        /* graphe indisponible : lecture normale, le dot garde son mouvement */
      }
      return original.call(this);
    };

    prototype.play = patched;
    return () => {
      if (prototype.play === patched) prototype.play = original;
    };
  }, []);

  /** Mesure RMS → niveau 0..1, lissé (attaque rapide, retombée douce). */
  useEffect(() => {
    if (typeof window === 'undefined') return;
    let buffer: Float32Array<ArrayBuffer> | null = null;
    let last = performance.now();

    const tick = (now: number): void => {
      frameRef.current = window.requestAnimationFrame(tick);
      const delta = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;

      let target = 0;
      const analyser = analyserRef.current;
      if (speakingRef.current && analyser && contextRef.current?.state === 'running') {
        if (!buffer || buffer.length !== analyser.fftSize) buffer = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(buffer);
        let sum = 0;
        for (let index = 0; index < buffer.length; index += 1) {
          const value = buffer[index] ?? 0;
          sum += value * value;
        }
        const rms = Math.sqrt(sum / buffer.length);
        target = Math.min(1, rms * 6.5);
      }

      // Activité de parole de l'utilisateur : décroît en ~350 ms.
      pulseRef.current *= Math.pow(0.06, delta);
      if (pulseRef.current < 0.004) pulseRef.current = 0;

      const current = levelRef.current;
      const goal = Math.max(target, pulseRef.current);
      const factor = goal > current ? 0.5 : 1 - Math.pow(0.02, delta);
      const next = current + (goal - current) * factor;
      levelRef.current = next < 0.002 ? 0 : next;

      // Rien à mesurer : on rend la main (aucune boucle qui tourne « pour rien »).
      if (!speakingRef.current && pulseRef.current === 0 && levelRef.current === 0) {
        if (frameRef.current) window.cancelAnimationFrame(frameRef.current);
        frameRef.current = 0;
      }
    };

    tickRef.current = tick;
    frameRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
      levelRef.current = 0;
    };
  }, []);

  const ensureRunning = useCallback(() => {
    if (frameRef.current) return;
    frameRef.current = window.requestAnimationFrame(tickRef.current);
  }, []);

  const pulse = useCallback(
    (strength: number) => {
      pulseRef.current = Math.min(1, Math.max(pulseRef.current, strength));
      ensureRunning();
    },
    [ensureRunning],
  );

  // La parole démarre : la mesure doit repartir même si la boucle s'était arrêtée.
  useEffect(() => {
    if (speaking) ensureRunning();
  }, [speaking, ensureRunning]);

  useEffect(() => {
    return () => {
      const context = contextRef.current;
      contextRef.current = null;
      analyserRef.current = null;
      sourcesRef.current = new WeakMap();
      if (context && context.state !== 'closed') void context.close().catch(() => undefined);
    };
  }, []);

  return { levelRef, pulse, prime };
}
