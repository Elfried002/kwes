/**
 * Conversation vocale continue : micro navigateur + SSE + ElevenLabs.
 *
 * Principes :
 * - Aucune capture avant un clic explicite (`activate`).
 * - Les états de l'Orb sont dérivés d'un fait réel : micro démarré, flux SSE
 *   ouvert, audio en lecture (événements `onplay` / `onended` de l'élément).
 * - Chaque phrase complète reçue du flux part immédiatement en synthèse ;
 *   la file audio n'attend jamais la fin de la réponse.
 * - Tour de parole strict : la reconnaissance reste active pendant que Kwes
 *   parle ; toute phrase reconnue (interim ou final) coupe net l'audio, annule
 *   le flux en cours et rend la parole à l'utilisateur. L'ancienne réponse ne
 *   reprend jamais : chaque tour porte une génération (`epoch`), et tout ce qui
 *   appartient à une génération dépassée est jeté (file, promesses, deltas SSE).
 * - L'écho du haut-parleur est reconnu en comparant la transcription à la
 *   phrase réellement en train d'être lue : couper là-dessus reviendrait à ce
 *   que Kwes s'interrompe lui-même.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { errorMessage, streamChat } from './api';
import { useKwesSpeech } from './use-kwes-speech';
import { useKwes } from '../state/KwesProvider';
import {
  FIRST_CONTACT_MESSAGE,
  SILENCE_MS,
  hasMetKwes,
  initialVoiceState,
  looksLikeEcho,
  markKwesMet,
  matchWakeWord,
  reduceVoice,
  shouldCutAudio,
  shouldOpenDiscovery,
  shouldSubmitOnSilence,
  splitSentences,
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
  /** Voix choisie dans les réglages (`null` = voix par défaut du serveur). */
  voiceId?: string | null;
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

  const introStartedRef = useRef(false);

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

  /* ---------- Audio (moteur partagé avec l'accueil) ---------- */

  /**
   * Une seule implémentation de la parole pour toute l'application : file
   * séquentielle, repli voix de l'appareil quand ElevenLabs ne renvoie pas
   * d'audio, coupe nette. Ce hook ne fait que traduire les faits observés en
   * événements de la machine à états.
   */
  const speech = useKwesSpeech({
    voiceId: options.voiceId,
    onNotice: (message) => callbacksRef.current.onNotice?.(message),
    onQueued: () => send({ type: 'AUDIO_QUEUED' }),
    onPlaying: () => send({ type: 'AUDIO_PLAYING' }),
    onEnded: () => send({ type: 'AUDIO_ENDED' }),
  });

  const nextEpoch = speech.beginTurn;
  const stopAudio = speech.stop;

  /** Synthèse lancée dès la phrase complète (parallèle à la lecture en cours). */
  const enqueueSpeech = useCallback(
    (sentence: string, epoch: number): void => {
      speech.enqueue(sentence, epoch, turnAbortRef.current?.signal);
    },
    [speech],
  );

  /* ---------- Tour de conversation ---------- */

  const submit = useCallback(
    (text: string): void => {
      const message = text.trim();
      if (!message) return;
      if (stateRef.current.phase !== 'listening') return;

      // Un nouveau tour invalide tout audio encore en vol (aucune reprise).
      const epoch = nextEpoch();
      send({ type: 'UTTERANCE', text: message });
      callbacksRef.current.onUserMessage(message);

      const controller = new AbortController();
      turnAbortRef.current = controller;
      const current = (): boolean => epoch === speech.epoch();
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
            if (!current() || !meta.conversation_id) return;
            if (meta.conversation_id === conversationIdRef.current) return;
            conversationIdRef.current = meta.conversation_id;
            callbacksRef.current.onConversationId?.(meta.conversation_id);
          },
          onDelta: (chunk) => {
            if (!current()) return; // réponse d'un tour déjà interrompu
            answer += chunk;
            send({ type: 'DELTA', text: chunk });
            buffer += chunk;
            const { sentences, rest } = splitSentences(buffer);
            buffer = rest;
            for (const sentence of sentences) enqueueSpeech(sentence, epoch);
          },
          onDone: (payload) => {
            if (!current()) return;
            if (buffer.trim()) enqueueSpeech(buffer, epoch);
            send({ type: 'STREAM_DONE' });
            callbacksRef.current.onAssistantMessage(payload.response ?? answer, {
              conversationId: payload.conversation_id ?? conversationIdRef.current,
              messageId: payload.message_id,
              taskId: payload.task_id ?? null,
              mock: payload.mock,
            });
          },
          onError: (error) => {
            if (!current() || controller.signal.aborted) return;
            send({ type: 'STREAM_ERROR', message: error.message });
            callbacksRef.current.onError?.(error.message);
          },
        },
        controller.signal,
      )
        .catch((cause: unknown) => {
          if (controller.signal.aborted || !current()) return;
          const message = errorMessage(cause);
          send({ type: 'STREAM_ERROR', message });
          callbacksRef.current.onError?.(message);
        })
        .finally(() => {
          if (turnAbortRef.current === controller) turnAbortRef.current = null;
        });
    },
    [enqueueSpeech, nextEpoch, send, speech],
  );

  /**
   * L'utilisateur reprend la parole : on coupe tout de suite, et on ne relance
   * jamais la réponse interrompue.
   */
  const bargeIn = useCallback(
    (transcript: string): boolean => {
      const current = stateRef.current;
      if (!current.active) return false;
      const audioBusy = speech.audioBusy();
      if (!audioBusy && !current.streaming && !shouldCutAudio(current)) return false;

      turnAbortRef.current?.abort();
      turnAbortRef.current = null;
      stopAudio();
      send({ type: 'BARGE_IN' });
      // La transcription dite pour interrompre est conservée : elle sera
      // envoyée après 1,2 s de silence, comme n'importe quelle phrase.
      if (transcript.trim()) send({ type: 'INTERIM', text: transcript.trim() });
      return true;
    },
    [send, speech, stopAudio],
  );

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

    // Aucune coupure ici : `onspeechstart` se déclenche aussi sur la propre
    // voix de Kwes. Le barge-in se décide sur du texte reconnu (voir onresult).
    recognition.onspeechstart = null;

    recognition.onresult = (event) => {
      let interim = '';
      let finalPart = '';
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (!result) continue;
        const alternative = result[0];
        if (!alternative) continue;
        if (result.isFinal) finalPart += ` ${alternative.transcript}`;
        else interim += alternative.transcript;
      }
      const candidate = `${finalPart} ${interim}`.replace(/\s+/g, ' ').trim();
      if (!candidate) return;

      const current = stateRef.current;
      if (!current.active) return;

      const speakingNow = current.phase === 'speaking' || speech.audioBusy();
      if (speakingNow && looksLikeEcho(candidate, speech.spokenText())) {
        // Écho du haut-parleur (Kwes s'entend) : on n'accumule rien, on ne coupe
        // rien. Toute autre parole coupe immédiatement, sans délai d'attente.
        return;
      }

      // Soit Kwes parle, soit il réfléchit : dans les deux cas l'utilisateur
      // reprend la main immédiatement.
      if (speakingNow || current.streaming) {
        bargeIn(candidate);
      }

      if (finalPart.trim()) {
        finalTextRef.current = `${finalTextRef.current} ${finalPart}`.replace(/\s+/g, ' ').trim();
      }
      interimTextRef.current = interim.trim();
      const pending = `${finalTextRef.current} ${interimTextRef.current}`
        .replace(/\s+/g, ' ')
        .trim();
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
  }, [armSilenceTimer, bargeIn, send, speech]);

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
      recognition.onerror = null;
      recognition.onstart = null;
      try {
        recognition.stop();
      } catch {
        /* déjà arrêté */
      }
    }
    setListening(false);
  }, [clearSilenceTimer]);

  /* ---------- Premier contact ---------- */

  /** Kwes parle en premier : une présentation, puis UNE question. */
  const openDiscovery = useCallback((): void => {
    if (introStartedRef.current) return;
    if (!shouldOpenDiscovery({
      metBefore: hasMetKwes(),
      standby: stateRef.current.standby,
      active: false,
    })) {
      return;
    }
    introStartedRef.current = true;
    markKwesMet();
    const epoch = nextEpoch();
    // Le texte réellement prononcé alimente le sous-titre (aucun faux contenu).
    send({ type: 'DELTA', text: FIRST_CONTACT_MESSAGE });
    enqueueSpeech(FIRST_CONTACT_MESSAGE, epoch);
  }, [enqueueSpeech, nextEpoch, send]);

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
    // Le micro vient d'être activé par un clic : la lecture est autorisée.
    openDiscovery();
  }, [openDiscovery, send, startRecognition, supported]);

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
      // Coupe la lecture et invalide tout ce qui est en vol.
      stopAudio();
    };
  }, [stopAudio, stopRecognition]);

  return { ...state, supported, listening, toggle, activate, deactivate, setStandby, speak };
}
