/**
 * Moteur de parole partagé : une seule implémentation pour l'écran vocal et
 * l'accueil.
 *
 * Il possède la file de synthèse et la lecture, et rien d'autre :
 *   - chaque phrase complète part en synthèse dès sa réception (`enqueue`) ;
 *   - la file est séquentielle : jamais deux voix superposées ;
 *   - si ElevenLabs ne renvoie pas d'audio (`audioBase64` vide : quota épuisé,
 *     panne, coupure), la phrase est prononcée par la voix de l'appareil
 *     (`speechSynthesis`, fr-FR) — la conversation reste possible ;
 *   - `stop()` coupe net : génération invalidée, file vidée, élément audio
 *     arrêté, voix de l'appareil annulée. Tout ce qui appartenait au tour
 *     précédent est jeté et ne reprend jamais.
 *
 * Le hook n'écrit aucun état React : il rapporte des faits observés
 * (`onPlaying` au démarrage réel de la lecture, `onEnded` à la fin réelle,
 * `onProgress` à la position réelle). Les écrans en déduisent leur phase.
 */

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { synthesizeSpeech, type SynthesizedSpeech } from './api';
import { estimateSpeechMs, playbackFraction } from './kwes-speech';
import { stripMarkdownForSpeech } from './voice-session';

interface QueueEntry {
  epoch: number;
  /** Texte réellement envoyé à la synthèse (markdown retiré). */
  text: string;
  promise: Promise<SynthesizedSpeech | null>;
}

export interface SpeechEngineOptions {
  /** Voix choisie dans les réglages (`null` = voix par défaut du serveur). */
  voiceId?: string | null;
  /** Information discrète : repli audio, moteur muet, etc. */
  onNotice?: (message: string) => void;
  /** Phrase acceptée et envoyée en synthèse. */
  onQueued?: (text: string) => void;
  /** La lecture de cette phrase vient réellement de commencer. */
  onPlaying?: (text: string) => void;
  /** Part réellement prononcée de la phrase en cours (0..1). */
  onProgress?: (text: string, fraction: number) => void;
  /** La lecture de cette phrase est réellement terminée (ou a échoué). */
  onEnded?: (text: string) => void;
  /** La voix de l'appareil parle (aucune mesure d'amplitude possible). */
  onDeviceVoice?: (active: boolean) => void;
}

export interface SpeechEngine {
  /** Envoie une phrase complète en synthèse puis en lecture. */
  enqueue: (sentence: string, epoch: number, signal?: AbortSignal) => void;
  /** Nouveau tour : invalide tout ce qui est en vol, sans toucher à la lecture. */
  beginTurn: () => number;
  /** Coupe net (interruption, navigation, démontage) et rend la nouvelle génération. */
  stop: () => number;
  /** Génération courante : tout ce qui porte un numéro périmé est ignoré. */
  epoch: () => number;
  /** Un élément audio est réellement en cours de lecture. */
  audioBusy: () => boolean;
  /** Phrases encore en file (synthèse ou lecture). */
  pending: () => number;
  /** Dernières phrases réellement lues — sert à reconnaître l'écho du haut-parleur. */
  spokenText: () => string;
}

export function useKwesSpeech(options: SpeechEngineOptions): SpeechEngine {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const epochRef = useRef(0);
  const queueRef = useRef<QueueEntry[]>([]);
  const pumpingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  /** Dernier extrait réellement lancé, même déjà terminé : on le coupe toujours
   * avant d'en lancer un autre (aucune superposition, même sur la fin d'un
   * extrait dont la surveillance a conclu 200 ms avant `ended`). */
  const lastAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioFinishedRef = useRef<(() => void) | null>(null);
  /** Les phrases réellement en cours de lecture servent à reconnaître l'écho. */
  const spokenRef = useRef<string[]>([]);

  const epoch = useCallback((): number => epochRef.current, []);

  /**
   * Voix de l'appareil. `speechSynthesis` ne signale pas toujours la fin :
   * un filet de sécurité (durée estimée) évite de bloquer la file pour autant.
   */
  const playWithDeviceVoice = useCallback(
    (text: string, epochOfTurn: number): Promise<void> =>
      new Promise<void>((resolve) => {
        const phrase = text.trim();
        const live = (): boolean => epochOfTurn === epochRef.current;
        let settled = false;
        let watchdog: number | null = null;

        const finish = (): void => {
          if (settled) return;
          settled = true;
          if (watchdog !== null) window.clearTimeout(watchdog);
          optionsRef.current.onDeviceVoice?.(false);
          resolve();
        };

        if (!phrase || typeof window === 'undefined' || !('speechSynthesis' in window)) {
          if (live()) optionsRef.current.onEnded?.(phrase);
          finish();
          return;
        }

        const synth = window.speechSynthesis;
        let utterance: SpeechSynthesisUtterance;
        try {
          utterance = new SpeechSynthesisUtterance(phrase);
        } catch {
          // Moteur incomplet : on ne bloque pas la conversation.
          if (live()) optionsRef.current.onEnded?.(phrase);
          finish();
          return;
        }
        utterance.lang = 'fr-FR';
        utterance.rate = 1.02;
        utterance.pitch = 0.95;
        const french = synth
          .getVoices()
          .find((voice) => voice.lang?.toLowerCase().startsWith('fr'));
        if (french) {
          try {
            utterance.voice = french;
          } catch {
            // Voix système non standard : la langue déclarée suffit au moteur.
          }
        }

        utterance.onstart = () => {
          if (!live()) {
            finish();
            return;
          }
          if (watchdog !== null) window.clearTimeout(watchdog);
          optionsRef.current.onDeviceVoice?.(true);
          optionsRef.current.onPlaying?.(phrase);
          optionsRef.current.onProgress?.(phrase, 0.02);
          // Filet : certains moteurs n'émettent ni `end` ni `boundary`.
          watchdog = window.setTimeout(finish, estimateSpeechMs(phrase) + 2500);
        };
        utterance.onboundary = (event) => {
          if (!live()) return;
          const chars = typeof event.charIndex === 'number' ? event.charIndex : 0;
          optionsRef.current.onProgress?.(
            phrase,
            Math.min(0.99, chars / Math.max(1, phrase.length)),
          );
        };
        utterance.onend = () => {
          if (live()) {
            optionsRef.current.onProgress?.(phrase, 1);
            optionsRef.current.onEnded?.(phrase);
          }
          finish();
        };
        utterance.onerror = () => {
          if (live()) optionsRef.current.onEnded?.(phrase);
          finish();
        };

        // Aucun moteur ne démarre (voix absente du système) : on ne bloque pas
        // la conversation plus d'une seconde et demie.
        watchdog = window.setTimeout(() => {
          if (settled) return;
          if (live()) {
            optionsRef.current.onNotice?.(
              "La voix de l’appareil n’a pas démarré. La phrase reste affichée en sous-titre.",
            );
            optionsRef.current.onEnded?.(phrase);
          }
          finish();
        }, 1500);

        try {
          synth.cancel();
          synth.speak(utterance);
        } catch {
          if (live()) optionsRef.current.onEnded?.(phrase);
          finish();
        }
      }),
    [],
  );

  /** Audio ElevenLabs : une seule lecture à la fois, progression réelle. */
  const playAudio = useCallback(
    (speech: SynthesizedSpeech, text: string, epochOfTurn: number): Promise<void> =>
      new Promise<void>((resolve) => {
        if (epochOfTurn !== epochRef.current) {
          resolve();
          return;
        }

        // Une seule lecture à la fois : jamais deux voix superposées.
        // `audioRef` est vidé dès qu'un extrait se termine ; on garde donc aussi
        // le dernier élément lancé pour pouvoir le taire avant le suivant.
        const previous = audioRef.current ?? lastAudioRef.current;
        if (previous) {
          try {
            previous.pause();
          } catch {
            /* déjà arrêtée */
          }
          audioFinishedRef.current?.();
        }

        const audio = new Audio(
          `data:${speech.mimeType ?? 'audio/mpeg'};base64,${speech.audioBase64}`,
        );
        audioRef.current = audio;
        lastAudioRef.current = audio;
        let settled = false;
        let monitor: number | null = null;
        let progress: number | null = null;

        const finish = (): void => {
          if (settled) return;
          settled = true;
          if (monitor !== null) window.clearInterval(monitor);
          if (progress !== null) window.clearInterval(progress);
          if (audioFinishedRef.current === finish) audioFinishedRef.current = null;
          if (audioRef.current === audio) audioRef.current = null;
          resolve();
        };
        audioFinishedRef.current = finish;

        audio.onplay = () => {
          spokenRef.current = [...spokenRef.current.slice(-2), text];
          const startedAt = Date.now();
          if (monitor !== null) window.clearInterval(monitor);
          if (progress !== null) window.clearInterval(progress);
          // Le sous-titre suit la position réelle de la lecture.
          progress = window.setInterval(() => {
            if (settled) return;
            optionsRef.current.onProgress?.(
              text,
              playbackFraction(audio.currentTime, audio.duration),
            );
          }, 100);
          // Surveillance : `ended` peut ne jamais arriver (onglet masqué, sortie
          // audio indisponible). On surveille la progression réelle.
          monitor = window.setInterval(() => {
            if (settled) return;
            const duration = audio.duration;
            if (Number.isFinite(duration) && duration > 0 && audio.currentTime >= duration - 0.2) {
              if (epochOfTurn === epochRef.current) {
                optionsRef.current.onProgress?.(text, 1);
                optionsRef.current.onEnded?.(text);
              }
              finish();
              return;
            }
            if (audio.currentTime <= 0.05 && Date.now() - startedAt > 4000) {
              optionsRef.current.onNotice?.(
                'Lecture audio impossible dans ce navigateur (aucune sortie audio). La réponse reste affichée en sous-titre.',
              );
              if (epochOfTurn === epochRef.current) optionsRef.current.onEnded?.(text);
              finish();
            }
          }, 500);
          if (epochOfTurn === epochRef.current) optionsRef.current.onPlaying?.(text);
        };
        audio.onended = () => {
          if (epochOfTurn === epochRef.current) {
            optionsRef.current.onProgress?.(text, 1);
            optionsRef.current.onEnded?.(text);
          }
          finish();
        };
        audio.onerror = () => {
          // Audio illisible : on ne prétend pas avoir parlé, on passe à la suite.
          optionsRef.current.onNotice?.(
            'Extrait audio illisible dans ce navigateur : la phrase reste affichée en sous-titre.',
          );
          if (epochOfTurn === epochRef.current) optionsRef.current.onEnded?.(text);
          finish();
        };

        void audio.play().catch(() => {
          optionsRef.current.onNotice?.(
            'Lecture audio bloquée par le navigateur : la phrase reste affichée en sous-titre.',
          );
          if (epochOfTurn === epochRef.current) optionsRef.current.onEnded?.(text);
          finish();
        });
      }),
    [],
  );

  const playSentence = useCallback(
    (speech: SynthesizedSpeech, text: string, epochOfTurn: number): Promise<void> => {
      const phrase = (text || speech.text || '').trim();
      if (!speech.audioBase64) {
        // Repli voix de l'appareil : même texte, prononcé par le système.
        return playWithDeviceVoice(phrase, epochOfTurn);
      }
      return playAudio(speech, phrase, epochOfTurn);
    },
    [playAudio, playWithDeviceVoice],
  );

  /**
   * File séquentielle. Le `pumpingRef` libéré AVANT la vérification finale
   * évite la course « une phrase arrive pendant que la boucle s'arrête ».
   */
  const pump = useCallback(async (): Promise<void> => {
    if (pumpingRef.current) return;
    pumpingRef.current = true;
    try {
      for (;;) {
        const entry = queueRef.current.shift();
        if (!entry) {
          pumpingRef.current = false;
          if (queueRef.current.length === 0) return;
          pumpingRef.current = true;
          continue;
        }
        if (entry.epoch !== epochRef.current) continue; // tour déjà interrompu
        const speech = await entry.promise;
        if (entry.epoch !== epochRef.current) continue; // interrompu pendant la synthèse
        if (!speech) {
          optionsRef.current.onNotice?.(
            'La synthèse vocale n’a pas abouti : la phrase reste affichée en sous-titre.',
          );
          optionsRef.current.onEnded?.(entry.text);
          continue;
        }
        try {
          await playSentence(speech, entry.text, entry.epoch);
        } catch {
          // Un lecteur qui jette ne doit jamais bloquer la file des phrases.
          if (entry.epoch === epochRef.current) optionsRef.current.onEnded?.(entry.text);
        }
      }
    } finally {
      pumpingRef.current = false;
    }
  }, [playSentence]);

  /** Synthèse lancée dès la phrase complète (parallèle à la lecture en cours). */
  const enqueue = useCallback(
    (sentence: string, epochOfTurn: number, signal?: AbortSignal): void => {
      const text = stripMarkdownForSpeech(sentence);
      if (!text || epochOfTurn !== epochRef.current) return;
      const promise = synthesizeSpeech(
        text,
        signal,
        optionsRef.current.voiceId ?? null,
      ).catch(() => null);
      queueRef.current.push({ epoch: epochOfTurn, text, promise });
      optionsRef.current.onQueued?.(text);
      void pump();
    },
    [pump],
  );

  const beginTurn = useCallback((): number => {
    epochRef.current += 1;
    queueRef.current = [];
    spokenRef.current = [];
    return epochRef.current;
  }, []);

  const stop = useCallback((): number => {
    epochRef.current += 1;
    queueRef.current = [];
    spokenRef.current = [];
    // Coupe aussi la voix de repli de l'appareil : le client doit pouvoir
    // interrompre Kwes à tout moment, quel que soit le moteur qui parle.
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
      } catch {
        /* moteur absent */
      }
      optionsRef.current.onDeviceVoice?.(false);
    }
    const audio = audioRef.current ?? lastAudioRef.current;
    audioRef.current = null;
    lastAudioRef.current = null;
    if (audio) {
      audio.onplay = null;
      audio.onended = null;
      audio.onerror = null;
      try {
        audio.pause();
        audio.currentTime = 0;
        audio.removeAttribute('src');
        audio.load();
      } catch {
        /* déjà libérée */
      }
    }
    const finish = audioFinishedRef.current;
    audioFinishedRef.current = null;
    finish?.();
    return epochRef.current;
  }, []);

  // Rien ne survit au démontage : aucune voix ne continue sur un autre écran.
  useEffect(() => {
    return () => {
      epochRef.current += 1;
      queueRef.current = [];
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* moteur absent */
        }
      }
      const audio = audioRef.current ?? lastAudioRef.current;
      audioRef.current = null;
      lastAudioRef.current = null;
      if (audio) {
        audio.onplay = null;
        audio.onended = null;
        audio.onerror = null;
        try {
          audio.pause();
        } catch {
          /* déjà arrêtée */
        }
      }
    };
  }, []);

  return useMemo(
    () => ({
      enqueue,
      beginTurn,
      stop,
      epoch,
      audioBusy: () => audioRef.current !== null,
      pending: () => queueRef.current.length,
      spokenText: () => spokenRef.current.join(' '),
    }),
    [beginTurn, enqueue, epoch, stop],
  );
}
