/**
 * Conversation vocale temps réel avec Gemini Live (Kwes).
 *
 * Le navigateur n'a jamais la clé du fournisseur : il obtient un ticket à usage
 * unique (60 s) puis ouvre la WebSocket `/voice/live`. Il envoie du PCM 16 bits
 * mono 16 kHz et reçoit du PCM 24 kHz, mis en file pour une lecture continue.
 *
 * Aucun état n'est simulé : `phase` ne change que sur un fait observable —
 * micro réellement ouvert, audio réellement en file, interruption signalée par
 * le serveur, erreur remontée par la WebSocket.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { buildVoiceUrl, createVoiceTicket } from './api';
import { getToken } from './auth';
import { getPreferences } from './prefs';
import type { VoiceSessionState } from './voice-session';

const INPUT_RATE = 16000;
const OUTPUT_RATE = 24000;
const CHUNK = 1024; // 64 ms à 16 kHz

interface LiveMessage {
  type: string;
  [key: string]: unknown;
}

export interface GeminiLive extends VoiceSessionState {
  supported: boolean;
  /** Vrai quand seul un toucher peut débloquer le micro (permission, audio suspendu). */
  needsGesture: boolean;
  listening: boolean;
  /** Dernier outil appelé pendant la session (nom technique masqué à l'écran). */
  tool: string | null;
  /** Niveau de sortie réel (0..1), lu par le dot. */
  levelRef: React.RefObject<number>;
  toggle: () => void;
  activate: () => void;
  deactivate: () => void;
  setStandby: (enabled: boolean) => void;
  speak: (text: string) => void;
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  const step = 0x8000;
  for (let index = 0; index < bytes.length; index += step) {
    binary += String.fromCharCode(...bytes.subarray(index, index + step));
  }
  return btoa(binary);
}

function floatToPcm16(input: Float32Array): Uint8Array {
  const out = new Uint8Array(input.length * 2);
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]));
    out[index * 2] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    out[index * 2 + 1] = (sample < 0 ? sample * 0x8000 : sample * 0x7fff) >> 8;
  }
  return out;
}

function pcm16ToFloat(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const count = Math.floor(bytes.length / 2);
  const samples = new Float32Array(new ArrayBuffer(count * 4));
  for (let index = 0; index < samples.length; index += 1) {
    const value = (bytes[index * 2] | (bytes[index * 2 + 1] << 8)) << 16 >> 16;
    samples[index] = value / 0x8000;
  }
  return samples;
}

export function useGeminiLive(): GeminiLive {
  const [state, setState] = useState({
    phase: 'idle' as VoiceSessionState['phase'],
    mode: 'fast' as VoiceSessionState['mode'],
    active: false,
    standby: false,
    armed: false,
    pending: '',
    answer: '',
    queued: 0,
    streaming: false,
    error: null as string | null,
    needsGesture: false,
  });
  const [tool, setTool] = useState<string | null>(null);
  const levelRef = useRef(0);

  const socketRef = useRef<WebSocket | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const inputCtxRef = useRef<AudioContext | null>(null);
  const outCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const queueRef = useRef<AudioBufferSourceNode[]>([]);
  const playingRef = useRef(0);
  const frameRef = useRef(0);
  const activeRef = useRef(false);
  // Intention de l'utilisateur : la conversation doit rester ouverte même si
  // la session Gemini tombe (durée de vie, réseau mobile, mise en veille).
  const desiredRef = useRef(false);
  const reconnectRef = useRef(0);
  const reopenRef = useRef<() => void>(() => {});
  const pendingAnswerRef = useRef('');
  // VAD local : l'API développeur ne clôt pas un tour sur un flux continu,
  // c'est donc le client qui signale début et fin de prise de parole.
  const vadRef = useRef({ speaking: false, silenceMs: 0, preroll: [] as string[] });

  const supported =
    typeof navigator !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && typeof WebSocket !== 'undefined';

  const stopPlayback = useCallback(() => {
    queueRef.current.forEach((node) => {
      try {
        node.stop();
      } catch {
        /* déjà arrêté */
      }
    });
    queueRef.current = [];
    playingRef.current = 0;
    setState((prev) => (prev.queued ? { ...prev, queued: 0 } : prev));
  }, []);

  const teardown = useCallback(() => {
    frameRef.current && cancelAnimationFrame(frameRef.current);
    frameRef.current = 0;
    stopPlayback();
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    micRef.current?.getTracks().forEach((track) => track.stop());
    micRef.current = null;
    void inputCtxRef.current?.close().catch(() => undefined);
    inputCtxRef.current = null;
    void outCtxRef.current?.close().catch(() => undefined);
    outCtxRef.current = null;
    analyserRef.current = null;
    socketRef.current?.close();
    socketRef.current = null;
    levelRef.current = 0;
  }, [stopPlayback]);

  const ensureOutput = useCallback(() => {
    if (outCtxRef.current) return outCtxRef.current;
    const context = new AudioContext({ sampleRate: OUTPUT_RATE });
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.connect(context.destination);
    analyserRef.current = analyser;
    outCtxRef.current = context;

    const tick = () => {
      const node = analyserRef.current;
      if (node) {
        const data = new Float32Array(node.fftSize);
        node.getFloatTimeDomainData(data);
        let sum = 0;
        for (let index = 0; index < data.length; index += 1) sum += data[index] * data[index];
        levelRef.current = Math.min(1, Math.sqrt(sum / data.length) * 3.2);
      }
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return context;
  }, []);

  const enqueueAudio = useCallback(
    (base64: string) => {
      const context = ensureOutput();
      const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
      const samples = pcm16ToFloat(bytes);
      if (!samples.length) return;
      const buffer = context.createBuffer(1, samples.length, OUTPUT_RATE);
      buffer.copyToChannel(samples, 0);
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(analyserRef.current ?? context.destination);
      const startAt = Math.max(context.currentTime, playingRef.current);
      source.start(startAt);
      playingRef.current = startAt + buffer.duration;
      queueRef.current.push(source);
      setState((prev) => ({ ...prev, phase: 'speaking', queued: prev.queued + 1, streaming: true }));
      source.onended = () => {
        queueRef.current = queueRef.current.filter((node) => node !== source);
        setState((prev) => {
          const queued = Math.max(0, prev.queued - 1);
          return { ...prev, queued, phase: queued === 0 ? 'listening' : prev.phase, streaming: queued > 0 };
        });
      };
    },
    [ensureOutput],
  );

  const handleMessage = useCallback(
    (message: LiveMessage) => {
      switch (message.type) {
        case 'ready':
          setState((prev) => ({ ...prev, phase: 'listening', error: null }));
          break;
        case 'state':
          if (message.value === 'listening') {
            setState((prev) => (prev.queued > 0 ? prev : { ...prev, phase: 'listening' }));
          }
          break;
        case 'mode':
          // Bascule Live rapide <-> raisonnement approfondi décidée par le serveur.
          setState((prev) => ({ ...prev, mode: message.value === 'thinking' ? 'thinking' : 'fast' }));
          break;
        case 'audio':
          if (typeof message.data === 'string') enqueueAudio(message.data);
          break;
        case 'interrupted':
          stopPlayback();
          setState((prev) => ({ ...prev, phase: 'listening', answer: '' }));
          pendingAnswerRef.current = '';
          break;
        case 'transcript': {
          const text = String(message.text ?? '');
          if (message.role === 'user') {
            setState((prev) => ({ ...prev, pending: text, phase: 'thinking' }));
          } else {
            pendingAnswerRef.current += (pendingAnswerRef.current ? ' ' : '') + text;
            setState((prev) => ({ ...prev, answer: pendingAnswerRef.current }));
          }
          break;
        }
        case 'tool':
          setTool(message.status === 'running' ? String(message.name ?? '') : null);
          setState((prev) => ({ ...prev, phase: message.status === 'running' ? 'thinking' : prev.phase }));
          break;
        case 'error':
          setState((prev) => ({
            ...prev,
            error: String(message.message ?? 'La voix est interrompue.'),
            phase: 'idle',
          }));
          break;
        case 'closed':
          setState((prev) => ({ ...prev, phase: 'idle', active: false }));
          break;
        default:
          break;
      }
    },
    [enqueueAudio, stopPlayback],
  );

  const activate = useCallback(async () => {
    if (activeRef.current || !supported) return;
    desiredRef.current = true;
    activeRef.current = true;
    setState((prev) => ({
      ...prev,
      active: true,
      error: null,
      needsGesture: false,
      phase: 'thinking',
      answer: '',
    }));
    pendingAnswerRef.current = '';

    try {
      // Le micro est demandé AVANT d'ouvrir la session : sur téléphone, la
      // permission peut prendre plusieurs secondes et la session Gemini se
      // fermait pour inactivité pendant que l'utilisateur répondait au système.
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micRef.current = mic;

      const context = new AudioContext({ sampleRate: INPUT_RATE });
      inputCtxRef.current = context;
      // Sur mobile, un contexte créé hors geste naît suspendu : sans reprise,
      // aucune trame ne part et l'agent n'entend rien.
      if (context.state === 'suspended') await context.resume();
      if (context.state !== 'running') {
        const blocked = new Error('audio-bloque');
        blocked.name = 'NotAllowedError';
        throw blocked;
      }

      // La session peut être en cours de restauration au montage de l'écran :
      // sans cette attente, le ticket partait sans jeton et l'ouverture échouait.
      let jeton = getToken();
      for (let attente = 0; attente < 16 && !jeton; attente += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500));
        jeton = getToken();
      }
      if (!jeton) throw new Error('session-absente');

      // Deux tentatives : un ticket expiré ou une coupure réseau passagère à
      // l'ouverture ne doit pas laisser l'utilisateur devant « impossible de
      // démarrer ». Le micro est déjà ouvert, on ne le redemande pas.
      let ticket: Awaited<ReturnType<typeof createVoiceTicket>> | null = null;
      let derniereErreur: unknown = null;
      for (let tentative = 0; tentative < 2; tentative += 1) {
        try {
          ticket = await createVoiceTicket(getPreferences().language);
          break;
        } catch (cause) {
          derniereErreur = cause;
          await new Promise((resolve) => setTimeout(resolve, 600 * (tentative + 1)));
        }
      }
      if (!ticket) {
        // Trace utile au support : aucune donnée sensible, seulement la cause.
        console.warn('Voix : ticket indisponible', derniereErreur);
        throw new Error('voix-reseau');
      }
      const socket = new WebSocket(buildVoiceUrl(ticket.ticket));
      socketRef.current = socket;
      socket.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(String(event.data)) as LiveMessage);
        } catch {
          /* trame ignorée */
        }
      };
      socket.onclose = () => {
        const intention = desiredRef.current;
        const etaitOuvert = activeRef.current;
        activeRef.current = false;
        teardown();
        if (!intention) {
          setState((prev) => ({ ...prev, phase: 'idle', active: false }));
          return;
        }
        // Ouverture réussie puis fermeture : on rouvre sans rien demander.
        // Première tentative en échec : on laisse le message d'erreur existant.
        if (!etaitOuvert) {
          setState((prev) => ({ ...prev, phase: 'idle', active: false }));
          return;
        }
        setState((prev) => ({ ...prev, active: true, phase: 'idle', error: null }));
        reconnectRef.current += 1;
        const delai = Math.min(400 * reconnectRef.current, 4000);
        window.setTimeout(() => {
          if (desiredRef.current && !activeRef.current) reopenRef.current();
        }, delai);
      };
      socket.onerror = () => {
        setState((prev) => ({ ...prev, error: 'Connexion vocale impossible.', phase: 'idle' }));
      };
      await new Promise<void>((resolve, reject) => {
        socket.addEventListener('open', () => { reconnectRef.current = 0; resolve(); }, { once: true });
        socket.addEventListener('error', () => reject(new Error('ws')), { once: true });
      });

      const source = context.createMediaStreamSource(mic);
      sourceRef.current = source;
      const processor = context.createScriptProcessor(CHUNK, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (event) => {
        const socket_ = socketRef.current;
        if (!socket_ || socket_.readyState !== WebSocket.OPEN) return;
        const samples = event.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let index = 0; index < samples.length; index += 1) sum += samples[index] * samples[index];
        const rms = Math.sqrt(sum / samples.length);
        const vad = vadRef.current;
        const frameMs = (CHUNK / INPUT_RATE) * 1000;
        const payload = toBase64(floatToPcm16(samples));

        if (!vad.speaking && rms > 0.015) {
          vad.speaking = true;
          vad.silenceMs = 0;
          socket_.send(JSON.stringify({ type: 'activity_start' }));
          vad.preroll.forEach((buffered) => socket_.send(JSON.stringify({ type: 'audio', data: buffered })));
          vad.preroll = [];
        }

        if (vad.speaking) {
          socket_.send(JSON.stringify({ type: 'audio', data: payload }));
          if (rms < 0.008) {
            vad.silenceMs += frameMs;
            // 300 ms : le seuil de 380 ms ajoutait une demi-seconde perçue avant
            // chaque réponse. Mesuré : premier son 720–900 ms côté serveur.
            if (vad.silenceMs > 300) {
              vad.speaking = false;
              vad.silenceMs = 0;
              socket_.send(JSON.stringify({ type: 'activity_end' }));
            }
          } else {
            vad.silenceMs = 0;
          }
        } else {
          // Pré-roll de 300 ms pour ne pas couper l'attaque du mot.
          vad.preroll.push(payload);
          if (vad.preroll.length > 5) vad.preroll.shift();
        }
      };
      source.connect(processor);
      processor.connect(context.destination);
      ensureOutput();
    } catch (error) {
      activeRef.current = false;
      teardown();
      const nom = error instanceof Error ? error.name : '';
      const message = error instanceof Error ? error.message : '';
      const geste = nom === 'NotAllowedError' || nom === 'SecurityError';
      const reseau = message === 'voix-reseau' || message === 'ws';
      const session = message === 'session-absente';
      setState((prev) => ({
        ...prev,
        active: false,
        phase: 'idle',
        // `geste` distingue ce que l'utilisateur peut débloquer d'un toucher
        // (permission, audio suspendu) d'une panne réseau ou serveur.
        error: geste
          ? 'Micro bloqué par le navigateur.'
          : session
            ? 'Votre session a expiré. Reconnectez-vous pour parler à Kwes.'
            : reseau
              ? 'Réseau vocal momentanément indisponible. Touchez pour réessayer.'
              : 'Impossible de démarrer la conversation vocale.',
        needsGesture: geste,
      }));
    }
  }, [ensureOutput, handleMessage, supported, teardown]);

  reopenRef.current = () => {
    void activate();
  };

  // Mobile : la mise en arrière-plan coupe le micro et la session. Au retour,
  // on rouvre sans que l'utilisateur ait à toucher quoi que ce soit.
  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    const auRetour = () => {
      if (document.visibilityState !== 'visible') return;
      if (!desiredRef.current || activeRef.current) return;
      reopenRef.current();
    };
    document.addEventListener('visibilitychange', auRetour);
    return () => document.removeEventListener('visibilitychange', auRetour);
  }, []);

  const deactivate = useCallback(() => {
    desiredRef.current = false;
    activeRef.current = false;
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'close' }));
    }
    teardown();
    setState((prev) => ({ ...prev, active: false, phase: 'idle', queued: 0, streaming: false }));
  }, [teardown]);

  const speak = useCallback((text: string) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || !text.trim()) return;
    pendingAnswerRef.current = '';
    setState((prev) => ({ ...prev, pending: text.trim(), answer: '', phase: 'thinking' }));
    socket.send(JSON.stringify({ type: 'text', text: text.trim() }));
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  return {
    ...state,
    supported,
    listening: state.active && state.phase === 'listening',
    tool,
    levelRef,
    toggle: () => (activeRef.current ? deactivate() : void activate()),
    activate: () => void activate(),
    deactivate,
    setStandby: () => undefined,
    speak,
  };
}
