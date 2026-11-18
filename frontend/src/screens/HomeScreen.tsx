/**
 * Accueil — Kwes parle, il n'écrit pas.
 *
 * Le personnage est la présence principale : il occupe le centre, passe en
 * `thinking` pendant le traitement, puis en `speaking` dès que la première
 * phrase complète est réellement prononcée. La réponse ne s'affiche jamais en
 * bloc : une seule ligne de sous-titre, révélée au rythme de la lecture, sous
 * le personnage. « Lire la réponse » ouvre la conversation complète.
 *
 * La parole vient de `use-kwes-speech` : même moteur que l'écran vocal (file
 * séquentielle, une seule voix à la fois, repli voix de l'appareil quand
 * le service vocal ne renvoie pas d'audio). Interruption : bouton « Arrêter », appui
 * sur le personnage, ou prise de parole au micro — la lecture est coupée net,
 * jamais reprise.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { errorMessage, streamChat } from '../lib/api';
import { useSession } from '../lib/auth';
import { firstName } from '../lib/format';
import { href } from '../lib/router';
import { readDraft, usePreferences, writeDraft } from '../lib/prefs';
import { useKwes } from '../state/KwesProvider';
import { Composer } from '../components/Composer';
import { Icon } from '../components/Icon';
import { KwesDroid } from '../components/KwesDroid';
import { useAudioLevel } from '../lib/use-audio-level';
import { useKwesSpeech } from '../lib/use-kwes-speech';
import { usePrefersReducedMotion } from '../lib/hooks';
import { speechEnvelope } from '../lib/kwes-speech';
import {
  homeAnnouncement,
  homeCaption,
  homeSpokenLine,
  initialHomeVoice,
  reduceHomeVoice,
} from '../lib/home-voice';

/**
 * Trois amorces concrètes, pas des arguments de vente : elles remplissent
 * simplement le champ pour que l'utilisateur puisse les ajuster avant d'envoyer.
 */
const SUGGESTIONS = [
  'Aide-moi à préparer ma journée.',
  'Résume où en sont mes projets.',
  'Rédige un message pour mon équipe.',
];

export function HomeScreen() {
  const { notifyChatStarted, notifyChatAnswered, notifyApiError, resetOrb, bumpRefresh, micActive } =
    useKwes();
  const prefs = usePreferences();
  const reduced = usePrefersReducedMotion();
  const [draft, setDraft] = useState(() => readDraft('home'));
  const [analysis, setAnalysis] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [focusSignal, setFocusSignal] = useState(0);
  const [deviceVoice, setDeviceVoice] = useState(false);
  const [state, dispatch] = useReducer(reduceHomeVoice, initialHomeVoice);

  const abortRef = useRef<AbortController | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;

  const speech = useKwesSpeech({
    voiceId: prefs.voiceId,
    onNotice: (message) => setNotice(message),
    onPlaying: (text) => {
      setNotice(null);
      dispatch({ type: 'PLAYING', text });
    },
    onProgress: (text, fraction) => dispatch({ type: 'PROGRESS', text, fraction }),
    onEnded: (text) => dispatch({ type: 'SPOKEN', text }),
    onDeviceVoice: setDeviceVoice,
  });

  const { levelRef: audioLevelRef, prime } = useAudioLevel(state.phase === 'speaking');
  /** Niveau réel (audio) ou cadence de la voix de l'appareil — jamais les deux. */
  const levelRef = useRef(0);

  useEffect(() => {
    if (state.phase !== 'speaking') {
      levelRef.current = 0;
      return;
    }
    const startedAt = performance.now();
    const timer = window.setInterval(() => {
      const measured = audioLevelRef.current;
      const fallback =
        deviceVoice && !reduced ? speechEnvelope((performance.now() - startedAt) / 1000) : 0;
      levelRef.current = Math.max(measured, fallback);
    }, 50);
    return () => {
      window.clearInterval(timer);
      levelRef.current = 0;
    };
  }, [audioLevelRef, deviceVoice, reduced, state.phase]);

  useEffect(() => {
    writeDraft('home', draft);
  }, [draft]);

  // Aucune voix ne continue quand on quitte l'écran.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const stopAll = useCallback((): void => {
    abortRef.current?.abort();
    abortRef.current = null;
    speech.stop();
    dispatch({ type: 'STOP' });
    resetOrb();
  }, [resetOrb, speech]);

  // Prise de parole au micro (dictée) : Kwes se tait immédiatement. On ne
  // réagit qu'au démarrage réel du micro (transition), jamais à un micro déjà
  // actif : un message dicté doit pouvoir être envoyé sans être coupé.
  const micWasActiveRef = useRef(micActive);
  useEffect(() => {
    const wasActive = micWasActiveRef.current;
    micWasActiveRef.current = micActive;
    if (!micActive || wasActive) return;
    if (state.phase !== 'speaking' && state.phase !== 'thinking') return;
    stopAll();
  }, [micActive, state.phase, stopAll]);

  const submit = async (): Promise<void> => {
    const message = draftRef.current.trim();
    if (!message) return;
    // Un nouvel envoi coupe net la réponse en cours : jamais deux voix.
    const epoch = speech.stop();
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    prime();
    setNotice(null);
    writeDraft('home', '');
    setDraft('');
    dispatch({ type: 'SEND' });
    notifyChatStarted();

    const live = (): boolean => !controller.signal.aborted && epoch === speech.epoch();
    let conversationId: string | null = null;

    try {
      await streamChat(
        {
          conversation_id: null,
          message,
          language: prefs.language,
          mode: analysis ? 'mission' : 'auto',
        },
        {
          onMeta: (meta) => {
            if (!live() || !meta.conversation_id) return;
            if (meta.conversation_id === conversationId) return;
            conversationId = meta.conversation_id;
            dispatch({ type: 'CONVERSATION', id: meta.conversation_id });
          },
          onDelta: (chunk) => {
            if (!live()) return;
            // Écrit = écrit : la réponse s'affiche, elle n'est jamais prononcée.
            dispatch({ type: 'DELTA', text: chunk });
          },
          onDone: (payload) => {
            if (!live()) return;
            conversationId = payload.conversation_id ?? conversationId;
            dispatch({ type: 'DONE', conversationId });
            setAnalysis(false);
            notifyChatAnswered();
            bumpRefresh();
          },
          onError: (error) => {
            if (!live()) return;
            dispatch({ type: 'ERROR', message: error.message });
            notifyApiError(error);
            setDraft((current) => (current.trim() ? current : message));
          },
        },
        controller.signal,
      );
    } catch (cause) {
      if (controller.signal.aborted || !live()) {
        resetOrb();
        return;
      }
      dispatch({ type: 'ERROR', message: errorMessage(cause) });
      notifyApiError(cause);
      setDraft((current) => (current.trim() ? current : message));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const session = useSession();
  const hello = firstName(session?.email, session?.displayName) || '';
  const caption = homeCaption(state);
  const speaking = state.phase === 'speaking';
  const working = state.phase === 'thinking';
  const visible = Boolean(caption) || speaking || working;

  const dotLabel = speaking ? 'Arrêter la réponse' : working ? 'Arrêter et revenir au repos' : 'Écrire à Kwes';

  const handleDot = (): void => {
    if (speaking || working) {
      stopAll();
      return;
    }
    setFocusSignal((current) => current + 1);
  };

  return (
    <div className="page home-dot" data-phase={state.phase}>
      <header className="home-hero">
        <p className="home-hero__hi">{hello ? `Bonjour ${hello}` : 'Bonjour'}</p>
        <h1 className="home-hero__title">Comment puis-je vous aider aujourd’hui&nbsp;?</h1>
      </header>

      <div className="home-dot__stage">
        <button
          type="button"
          className="home-dot__figure"
          onClick={handleDot}
          aria-label={dotLabel}
          data-active={speaking || working ? 'true' : 'false'}
        >
          <KwesDroid phase={state.phase} levelRef={levelRef} className="home-dot__canvas" />
        </button>

        <div className="home-dot__caption">
          <p
            className="home-dot__subtitle"
            data-visible={visible ? 'true' : 'false'}
            data-tone={state.error ? 'error' : 'neutral'}
            aria-live="polite"
          >
            <span aria-hidden="true">{caption || '\u00A0'}</span>
            <span className="sr-only">{homeSpokenLine(state)}</span>
          </p>

          {state.answer ? (
            <p className="home-answer" tabIndex={0} aria-label="Réponse de Kwes">{state.answer}</p>
          ) : null}

          <div className="home-dot__actions">
            {speaking || working ? (
              <button type="button" className="home-dot__stop" onClick={stopAll}>
                Arrêter
              </button>
            ) : null}
          </div>

          {notice ? <p className="home-dot__notice">{notice}</p> : null}
        </div>

        <p className="sr-only" role="status" aria-live="polite">
          {homeAnnouncement(state)}
        </p>
      </div>

      <div className="home-dot__bottom">
        <Composer
          value={draft}
          onChange={setDraft}
          onSubmit={() => {
            void submit();
          }}
          busy={working}
          onStop={stopAll}
          onVoice={() => {
            window.location.hash = href({ name: 'voice' });
          }}
          placeholder="Demander à Kwes"
          autoFocus
          micAllowed={prefs.voiceEnabled}
          analysis={{ active: analysis, onToggle: () => setAnalysis((current) => !current) }}
          focusSignal={focusSignal}
        />

        {state.phase === 'idle' && !state.sentence && !state.error && !state.answer ? (
          <div className="home-actions" aria-label="Actions rapides">
            <a className="home-action" href={href({ name: 'voice' })}>
              <span className="home-action__icon" aria-hidden="true">
                <Icon name="mic" size={18} />
              </span>
              <span className="home-action__label">Parler à Kwes</span>
              <span className="home-action__arrow" aria-hidden="true">↗</span>
            </a>
            <button
              type="button"
              className="home-action"
              onClick={() => {
                setDraft('Cherche sur le web ');
                setFocusSignal((current) => current + 1);
              }}
            >
              <span className="home-action__icon" aria-hidden="true">
                <Icon name="spark" size={18} />
              </span>
              <span className="home-action__label">Chercher des sources</span>
              <span className="home-action__arrow" aria-hidden="true">↗</span>
            </button>
          </div>
        ) : null}

        {state.phase === 'idle' && !state.sentence && !state.error && !state.answer ? (
          <div className="home-dot__suggestions" aria-label="Suggestions">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className="home-dot__suggestion"
                onClick={() => {
                  setDraft(suggestion);
                  setFocusSignal((current) => current + 1);
                }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
