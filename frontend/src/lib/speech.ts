import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Dictée navigateur (Web Speech API), utilisée seulement après action explicite
 * de l'utilisateur. Aucun accès micro au chargement.
 */

interface SpeechAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechResult {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: SpeechAlternative;
}

interface SpeechResultList {
  readonly length: number;
  readonly [index: number]: SpeechResult;
}

interface SpeechResultEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechResultList;
}

interface SpeechErrorEvent extends Event {
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
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function getRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const candidate = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

interface UseDictationOptions {
  lang?: string;
  onTranscript: (text: string) => void;
  onStart?: () => void;
  onEnd?: () => void;
}

export interface Dictation {
  supported: boolean;
  listening: boolean;
  error: string | null;
  start: () => void;
  stop: () => void;
}

export function useDictation({ lang = 'fr-FR', onTranscript, onStart, onEnd }: UseDictationOptions): Dictation {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const callbacks = useRef({ onTranscript, onStart, onEnd });
  callbacks.current = { onTranscript, onStart, onEnd };

  const supported = typeof window !== 'undefined' && getRecognitionConstructor() !== null;

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Constructor = getRecognitionConstructor();
    if (!Constructor) {
      setError("La reconnaissance vocale n'est pas prise en charge par ce navigateur.");
      return;
    }
    if (recognitionRef.current) return;

    setError(null);
    const recognition = new Constructor();
    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;

    recognition.onstart = () => {
      setListening(true);
      callbacks.current.onStart?.();
    };

    recognition.onresult = (event) => {
      let finalText = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (!result || !result.isFinal) continue;
        const alternative = result[0];
        if (alternative) finalText += alternative.transcript;
      }
      const text = finalText.trim();
      if (text) callbacks.current.onTranscript(text);
    };

    recognition.onerror = (event) => {
      const messages: Record<string, string> = {
        'not-allowed': 'Accès au microphone refusé. Autorisez-le dans le navigateur.',
        'service-not-allowed': 'Service de reconnaissance vocale bloqué par le navigateur.',
        'no-speech': 'Aucune parole détectée. Réessayez.',
        'audio-capture': 'Aucun microphone disponible.',
        network: 'La reconnaissance vocale nécessite une connexion réseau.',
        aborted: '',
      };
      const message = messages[event.error] ?? `Dictée interrompue (${event.error}).`;
      if (message) setError(message);
    };

    recognition.onend = () => {
      recognitionRef.current = null;
      setListening(false);
      callbacks.current.onEnd?.();
    };

    try {
      recognition.start();
    } catch {
      recognitionRef.current = null;
      setListening(false);
      setError('Impossible de démarrer la dictée.');
    }
  }, [lang]);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  return { supported, listening, error, start, stop };
}
