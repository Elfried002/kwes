/**
 * Conversation vocale continue : micro navigateur + SSE + ElevenLabs.
 *
 * Principes :
 * - Aucune capture avant un clic explicite (`activate`).
 * - Les états de l'Orb sont dérivés d'un fait réel : micro démarré, flux SSE
 *   ouvert, audio en lecture (événements `onplay` / `onended` de l'élément).
 * - Chaque phrase complète reçue du flux part immédiatement en synthèse ;
 *   la file audio n'attend jamais la fin de la réponse.
 * - Barge-in : la parole pendant la lecture coupe l'audio, annule le flux en
 *   cours et repasse en écoute.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage, streamChat, synthesizeSpeech, type SynthesizedSpeech } from './api';
import { useKwes } from '../state/KwesProvider';
import {
  SILENCE_MS,
  initialVoiceState,
  matchWakeWord,
  reduceVoice,
  shouldCutAudio,
  shouldSubmitOnSilence,
  splitSentences,
  stripMarkdownForSpeech,
  type VoiceEvent,
  type VoicePhase,
  type VoiceSessionState,
} from './voice-session';

/* ---------- Web Speech API (typée localement, pas de dépendance) ---------- */

interface SpeechAlternativeLike {
  transcript: string;
}

interface SpeechResultLike {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: SpeechAlternativeLike;
}

interface SpeechResultListLike {
  readonly length: number;
  readonly [index: number]: SpeechResultLike;
}

interface SpeechResultEventLike extends Event {
  readonly resultIndex: number;
  readonly results: SpeechResultListLike;
}

interface SpeechErrorEventLike extends Event {
  readonly error: string;
}

interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechResultEventLike) => void) | null;
  onerror: ((event: SpeechErrorEventLike) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

export function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const candidate = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

/* ---------- Hook ---------- */

export interface VoiceTurnInfo {
  conversationId?: string;
  messageId?: string;
  taskId?: string | null;
  mock?: boolean;
}

export interface VoiceConversationOptions {
  conversationId?: string;
  language?: string;
  /** Appelé pour chaque phrase réellement envoyée au serveur. */
  onUserMessage: (text: string) => void;
  /** Appelé une fois la réponse complète reçue (message persistant côté serveur). */
  onAssistantMessage: (text: string, info: VoiceTurnInfo) => void;
  /** Première réponse d'une nouvelle conversation : l'appelant peut changer d'URL. */
  onConversationId?: (id: string) => void;
  onError?: (message: string) => void;
  /** Info discrète (repli audio, etc.). */
  onNotice?: (message: string) => void;
}

export interface VoiceConversation extends VoiceSessionState {
  supported: boolean;
  /** Reconnaissance effectivement en cours (fait, pas intention). */
  listening: boolean;
  toggle: () => void;
  activate: () => void;
  deactivate: () => void;
  setStandby: (enabled: boolean) => void;
  /** Soumission manuelle d'une phrase (bouton « Envoyer » du mode vocal). */
  speak: (text: string) => void;
}

/** Délai minimal avant d'accepter un barge-in : évite l'auto-interruption par le haut-parleur. */
const BARGE_IN_GUARD_MS = 350;

export function useVoiceConversation(options: VoiceConversationOptions): VoiceConversation {
  const { setMicActive, notifyChatStarted, notifyAudioStart, notifyAudioEnd, dispatchOrb, resetOrb } =
    useKwes();

  const [state, setState] = useState<VoiceSessionState>(initialVoiceState);
  const stateRef = useRef<VoiceSessionState>(initialVoiceState);
  const [listening, setListening] = useState(false);

  const callbacksRef = useRef(options);
  callbacksRef.current = options;

  const supported = useMemo(() => getSpeechRecognition() !== null, []);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const restartTimerRef = useRef<number | null>(null);
  const silenceTimerRef = useRef<number | null>(null);
  const lastVoiceAtRef = useRef<number>(0);
  const finalTextRef = useRef('');
  const interimTextRef = useRef('');

  const conversationIdRef = useRef<string | undefined>(options.conversationId);
  const turnAbortRef = useRef<AbortController | null>(null);
  const audioQueueRef = useRef<Array<Promise<SynthesizedSpeech | null>>>([]);
  const drainingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioFinishedRef = useRef<(() => void) | null>(null);
  const speakingSinceRef = useRef(0);

  /** Réduction synchrone : les handlers du micro lisent un état à jour. */
  const send = useCallback((event: VoiceEvent): VoiceSessionState => {
    const next = reduceVoice(stateRef.current, event);
    stateRef.current = next;
    setState(next);
    return next;
  }, []);

  useEffect(() => {
    conversationIdRef.current = options.conversationId;
  }, [options.conversationId]);

  /* ---------- Audio ---------- */

  const playSpeech = useCallback(
    (speech: SynthesizedSpeech): Promise<void> =>
      new Promise<void>((resolve) => {
        if (!speech.audioBase64) {
          resolve();
          return;
        }
        const audio = new Audio(
          `data:${speech.mimeType ?? 'audio/mpeg'};base64,${speech.audioBase64}`,
        );
        audioRef.current = audio;
        let settled = false;
        let monitor: number | null = null;
        const finish = (): void => {
          if (settled) return;
          settled = true;
          if (monitor !== null) window.clearInterval(monitor);
          audioFinishedRef.current = null;
          if (audioRef.current === audio) audioRef.current = null;
          resolve();
        };
        audioFinishedRef.current = finish;

        audio.onplay = () => {
          speakingSinceRef.current = Date.now();
          const startedAt = Date.now();
          if (monitor !== null) window.clearInterval(monitor);
          // Surveillance : `ended` peut ne jamais arriver (onglet masqué, sortie
          // audio indisponible). On surveille la progression réelle de la lecture.
          monitor = window.setInterval(() => {
            if (settled) return;
            const duration = audio.duration;
            if (Number.isFinite(duration) && duration > 0 && audio.currentTime >= duration - 0.2) {
              send({ type: 'AUDIO_ENDED' });
              finish();
              return;
            }
            if (audio.currentTime <= 0.05 && Date.now() - startedAt > 4000) {
              callbacksRef.current.onNotice?.(
                'Lecture audio impossible dans ce navigateur (aucune sortie audio). La réponse reste affichée en texte.',
              );
              send({ type: 'AUDIO_ENDED' });
              finish();
            }
          }, 500);
          send({ type: 'AUDIO_PLAYING' });
        };
        audio.onended = () => {
          send({ type: 'AUDIO_ENDED' });
          finish();
        };
        audio.onerror = () => {
          // Audio illisible : on ne prétend pas avoir parlé, on passe à la suite.
          callbacksRef.current.onNotice?.(
            'Extrait audio illisible dans ce navigateur : la réponse reste affichée en texte.',
          );
          send({ type: 'AUDIO_ENDED' });
          finish();
        };

        void audio.play().catch(() => {
          callbacksRef.current.onNotice?.(
            'Lecture audio bloquée par le navigateur : cliquez à nouveau sur le micro. Le texte reste disponible.',
          );
          send({ type: 'AUDIO_ENDED' });
          finish();
        });
      }),
    [send],
  );

  const drainAudio = useCallback(async (): Promise<void> => {
    if (drainingRef.current) return;
    drainingRef.current = true;
    try {
      while (audioQueueRef.current.length > 0) {
        const pending = audioQueueRef.current.shift();
        if (!pending) continue;
        const speech = await pending;
        if (!speech) {
          send({ type: 'AUDIO_ENDED' });
          continue;
        }
        if (!speech.audioBase64) {
          if (speech.reason) callbacksRef.current.onNotice?.(speech.reason);
          send({ type: 'AUDIO_ENDED' });
          continue;
        }
        await playSpeech(speech);
      }
    } finally {
      drainingRef.current = false;
    }
  }, [playSpeech, send]);

  /** Synthèse lancée dès la phrase complète (parallèle à la lecture en cours). */
  const enqueueSpeech = useCallback(
    (sentence: string): void => {
      const text = stripMarkdownForSpeech(sentence);
      if (!text) return;
      const signal = turnAbortRef.current?.signal;
      const promise = synthesizeSpeech(text, signal).catch(() => null);
      audioQueueRef.current.push(promise);
      send({ type: 'AUDIO_QUEUED' });
      void drainAudio();
    },
    [drainAudio, send],
  );

  const stopAudio = useCallback((): void => {
    audioQueueRef.current = [];
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    audioFinishedRef.current?.();
  }, []);

  /* ---------- Tour de conversation ---------- */

  const submit = useCallback(
    (text: string): void => {
      const message = text.trim();
      if (!message) return;
      const already = stateRef.current;
      if (already.phase !== 'listening') return;

      send({ type: 'UTTERANCE', text: message });
      callbacksRef.current.onUserMessage(message);

      const controller = new AbortController();
      turnAbortRef.current = controller;
      let buffer = '';
      let answer = '';

      void streamChat(
        {
          conversation_id: conversationIdRef.current ?? null,
          message,
          language: callbacksRef.current.language ?? 'fr',
          mode: 'auto',
        },
        {
          onMeta: (meta) => {
            if (!meta.conversation_id) return;
            if (meta.conversation_id === conversationIdRef.current) return;
            conversationIdRef.current = meta.conversation_id;
            callbacksRef.current.onConversationId?.(meta.conversation_id);
          },
          onDelta: (chunk) => {
            answer += chunk;
            send({ type: 'DELTA', text: chunk });
            buffer += chunk;
            const { sentences, rest } = splitSentences(buffer);
            buffer = rest;
            for (const sentence of sentences) enqueueSpeech(sentence);
          },
          onDone: (payload) => {
            if (buffer.trim()) enqueueSpeech(buffer);
            send({ type: 'STREAM_DONE' });
            callbacksRef.current.onAssistantMessage(payload.response ?? answer, {
              conversationId: payload.conversation_id ?? conversationIdRef.current,
              messageId: payload.message_id,
              taskId: payload.task_id ?? null,
              mock: payload.mock,
            });
          },
          onError: (error) => {
            send({ type: 'STREAM_ERROR', message: error.message });
            callbacksRef.current.onError?.(error.message);
          },
        },
        controller.signal,
      )
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          const message = errorMessage(cause);
          send({ type: 'STREAM_ERROR', message });
          callbacksRef.current.onError?.(message);
        })
        .finally(() => {
          if (turnAbortRef.current === controller) turnAbortRef.current = null;
        });
    },
    [enqueueSpeech, send],
  );

  const bargeIn = useCallback((): void => {
    const current = stateRef.current;
    if (!shouldCutAudio(current) && !current.streaming) return;
    turnAbortRef.current?.abort();
    turnAbortRef.current = null;
    stopAudio();
    finalTextRef.current = '';
    interimTextRef.current = '';
    send({ type: 'BARGE_IN' });
  }, [send, stopAudio]);

  /* ---------- Reconnaissance vocale ---------- */

  const clearSilenceTimer = useCallback((): void => {
    if (silenceTimerRef.current !== null) {
      window.clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const commitUtterance = useCallback((): void => {
    clearSilenceTimer();
    const text = `${finalTextRef.current} ${interimTextRef.current}`.replace(/\s+/g, ' ').trim();
    finalTextRef.current = '';
    interimTextRef.current = '';
    if (!text) return;

    const current = stateRef.current;
    if (!current.active || current.phase !== 'listening') return;

    if (!current.armed) {
      // Veille : seul le mot d'activation réveille Kwes.
      const wake = matchWakeWord(text);
      if (!wake.matched) return;
      send({ type: 'WAKE_WORD' });
      if (wake.rest) submit(wake.rest);
      return;
    }

    const wake = matchWakeWord(text);
    submit(wake.matched && wake.rest ? wake.rest : text);
  }, [clearSilenceTimer, send, submit]);

  const armSilenceTimer = useCallback((): void => {
    clearSilenceTimer();
    lastVoiceAtRef.current = Date.now();
    silenceTimerRef.current = window.setTimeout(() => {
      const elapsed = Date.now() - lastVoiceAtRef.current;
      const pending = `${finalTextRef.current} ${interimTextRef.current}`.trim();
      if (!shouldSubmitOnSilence(pending, elapsed, SILENCE_MS)) return;
      commitUtterance();
    }, SILENCE_MS);
  }, [clearSilenceTimer, commitUtterance]);

  const startRecognition = useCallback((): void => {
    const Constructor = getSpeechRecognition();
    if (!Constructor || recognitionRef.current) return;
    const recognition = new Constructor();
    recognition.lang = callbacksRef.current.language === 'en' ? 'en-US' : 'fr-FR';
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setListening(true);
      send({ type: 'MIC_READY' });
    };

    recognition.onspeechstart = () => {
      const current = stateRef.current;
      if (!current.active) return;
      if (current.phase === 'speaking' || current.phase === 'thinking') {
        // Barge-in : l'utilisateur reprend la parole. Garde anti-écho au début
        // de la lecture (le haut-parleur peut être capté par le micro).
        if (current.phase === 'speaking' && Date.now() - speakingSinceRef.current < BARGE_IN_GUARD_MS) {
          return;
        }
        bargeIn();
      }
      armSilenceTimer();
    };

    recognition.onresult = (event) => {
      let interim = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (!result) continue;
        const alternative = result[0];
        if (!alternative) continue;
        if (result.isFinal) {
          finalTextRef.current = `${finalTextRef.current} ${alternative.transcript}`.trim();
        } else {
          interim += alternative.transcript;
        }
      }
      interimTextRef.current = interim;
      const pending = `${finalTextRef.current} ${interim}`.replace(/\s+/g, ' ').trim();
      if (!pending) return;
      send({ type: 'INTERIM', text: pending });
      armSilenceTimer();
    };

    recognition.onerror = (event) => {
      const messages: Record<string, string> = {
        'not-allowed': 'Accès au microphone refusé. Autorisez-le dans le navigateur puis réessayez.',
        'service-not-allowed': 'Le service de reconnaissance vocale est bloqué par le navigateur.',
        'audio-capture': 'Aucun microphone disponible sur cet appareil.',
        network: 'La reconnaissance vocale nécessite une connexion réseau.',
      };
      const message = messages[event.error];
      if (message) {
        send({ type: 'MIC_FAILED', message });
        callbacksRef.current.onError?.(message);
      }
      // 'no-speech' et 'aborted' sont normaux en continu : on relance sans bruit.
    };

    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
      if (!stateRef.current.active) return;
      // Chrome coupe la reconnaissance après un silence : on la relance.
      restartTimerRef.current = window.setTimeout(() => {
        restartTimerRef.current = null;
        if (stateRef.current.active) startRecognition();
      }, 250);
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setListening(false);
      const message = 'Impossible de démarrer la reconnaissance vocale.';
      send({ type: 'MIC_FAILED', message });
      callbacksRef.current.onError?.(message);
    }
  }, [armSilenceTimer, bargeIn, send]);

  const stopRecognition = useCallback((): void => {
    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
    clearSilenceTimer();
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    if (recognition) {
      recognition.onend = null;
      recognition.onresult = null;
      recognition.onspeechstart = null;
      recognition.onerror = null;
      try {
        recognition.stop();
      } catch {
        /* déjà arrêté */
      }
    }
    setListening(false);
  }, [clearSilenceTimer]);

  /* ---------- API publique ---------- */

  const activate = useCallback((): void => {
    if (!supported) {
      const message =
        "La reconnaissance vocale n'est pas prise en charge par ce navigateur. Utilisez la saisie texte.";
      send({ type: 'MIC_FAILED', message });
      callbacksRef.current.onError?.(message);
      return;
    }
    if (stateRef.current.active) return;
    send({ type: 'ACTIVATE' });
    startRecognition();
  }, [send, startRecognition, supported]);

  const deactivate = useCallback((): void => {
    send({ type: 'DEACTIVATE' });
    turnAbortRef.current?.abort();
    turnAbortRef.current = null;
    stopAudio();
    finalTextRef.current = '';
    interimTextRef.current = '';
    stopRecognition();
  }, [send, stopAudio, stopRecognition]);

  const toggle = useCallback((): void => {
    if (stateRef.current.active) deactivate();
    else activate();
  }, [activate, deactivate]);

  const setStandby = useCallback(
    (enabled: boolean): void => {
      send({ type: 'STANDBY', enabled });
      if (enabled) {
        finalTextRef.current = '';
        interimTextRef.current = '';
      }
    },
    [send],
  );

  const speak = useCallback(
    (text: string): void => {
      if (!stateRef.current.active) return;
      if (stateRef.current.phase !== 'listening') return;
      submit(text);
    },
    [submit],
  );

  /* ---------- Orb : uniquement des faits observés ---------- */

  const prevPhaseRef = useRef<VoicePhase>('idle');
  useEffect(() => {
    const phase = state.phase;
    const previous = prevPhaseRef.current;
    if (phase === previous) return;
    prevPhaseRef.current = phase;

    // Sortie de lecture : l'audio est réellement terminé (onended).
    if (previous === 'speaking') notifyAudioEnd();

    if (phase === 'listening') {
      if (previous === 'speaking') {
        // La réponse est terminée : on passe par `response` pour revenir écouter.
        dispatchOrb('CHAT_RESPONSE');
      }
      setMicActive(true);
    } else if (phase === 'thinking') {
      setMicActive(false);
      notifyChatStarted();
    } else if (phase === 'speaking') {
      notifyAudioStart();
    } else if (phase === 'idle') {
      setMicActive(false);
      resetOrb();
    }
  }, [
    state.phase,
    dispatchOrb,
    notifyAudioEnd,
    notifyAudioStart,
    notifyChatStarted,
    resetOrb,
    setMicActive,
  ]);

  /* ---------- Nettoyage ---------- */

  useEffect(() => {
    return () => {
      stopRecognition();
      turnAbortRef.current?.abort();
      audioQueueRef.current = [];
      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        audioRef.current = null;
      }
    };
  }, [stopRecognition]);

  return { ...state, supported, listening, toggle, activate, deactivate, setStandby, speak };
}
