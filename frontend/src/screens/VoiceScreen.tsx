/**
 * Écran vocal plein écran : noir, un seul dot vivant, chrome minimal.
 *
 * Rien n'est simulé ici : le dot lit la phase réelle de `useGeminiLive`, qui ne
 * change que sur des faits observables (micro ouvert, audio réellement reçu du
 * flux Gemini, interruption signalée par le serveur).
 *   - appui sur le dot = démarrer l'écoute ;
 *   - Gemini répond en audio natif, sans étape de synthèse séparée ;
 *   - parler pendant la réponse interrompt (barge-in côté modèle) ;
 *   - après la réponse, retour automatique en écoute ;
 *   - bouton fermer = retour à l'accueil.
 */

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { href, navigate, type Route } from '../lib/router';
import { useGeminiLive } from '../lib/use-gemini-live';
import { useAudioLevel } from '../lib/use-audio-level';
import { useSession } from '../lib/auth';
import { stripMarkdownForSpeech, voiceAnnouncement } from '../lib/voice-session';
import { Icon, type IconName } from '../components/Icon';
import { type DotPhase } from '../components/orb/LivingDot';
import { KwesDroid } from '../components/KwesDroid';
import '../styles/voice-screen.css';

interface MenuEntry {
  label: string;
  route: Route;
  icon: IconName;
}

/** Mêmes entrées que la navigation de l'application, sans la barre latérale. */
const MENU: MenuEntry[] = [
  { label: 'Accueil', route: { name: 'home' }, icon: 'home' },
  { label: 'Ce qu’il fait', route: { name: 'tasks' }, icon: 'activity' },
  { label: 'Il attend votre accord', route: { name: 'approvals' }, icon: 'shield' },
  { label: 'Vos échanges', route: { name: 'conversations' }, icon: 'history' },
  { label: 'Réglages', route: { name: 'settings' }, icon: 'settings' },
];

const CAPTION_MAX = 150;

/** Première phrase de la réponse, sans mise en forme, pour la ligne unique. */
function captionFromAnswer(answer: string): string {
  const clean = stripMarkdownForSpeech(answer);
  if (!clean) return '';
  if (clean.length <= CAPTION_MAX) return clean;
  const cut = clean.slice(0, CAPTION_MAX);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 40 ? cut.slice(0, lastSpace) : cut).trim()}…`;
}

export function VoiceScreen() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [captionVisible, setCaptionVisible] = useState(false);

  const pendingTextRef = useRef<string | null>(null);
  const previousPendingRef = useRef('');
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const voice = useGeminiLive();

  // Entrer dans l'espace vocal tente de démarrer la conversation tout de suite.
  // Sur iOS/Safari, le micro et l'audio exigent un geste utilisateur : si le
  // navigateur refuse le démarrage automatique, on affiche une seule action
  // « Touchez pour parler » — jamais un bouton micro à activer/désactiver.
  const session = useSession();
  const startedRef = useRef(false);
  const [needsStart, setNeedsStart] = useState(false);

  // Le démarrage automatique attend que la session soit disponible : sinon le
  // ticket vocal part sans jeton, reçoit 401 et l'écran reste muet.
  useEffect(() => {
    if (!session?.token) return;
    if (startedRef.current) return;
    startedRef.current = true;
    void voice.activate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.token]);

  useEffect(() => {
    if (voice.active) {
      setNeedsStart(false);
      return;
    }
    if (voice.error) setNeedsStart(true);
  }, [voice.active, voice.error]);

  // `pulse` anime le dot sur la parole reconnue ; le niveau réel vient de
  // l'analyseur branché sur la sortie audio de Gemini (aucun élément <audio>).
  const { pulse, prime } = useAudioLevel(voice.phase === 'speaking');
  const levelRef = voice.levelRef;

  const dotPhase: DotPhase = voice.error ? 'error' : voice.phase;
  const captionText = voice.error ?? (voice.pending || captionFromAnswer(voice.answer));

  /* ---------- Une seule ligne de sous-titre, qui s'efface ---------- */

  useEffect(() => {
    if (!captionText) {
      setCaptionVisible(false);
      return;
    }
    setCaptionVisible(true);
    // Tant que Kwes parle ou qu'une erreur est affichée, la ligne reste lisible.
    if (voice.phase === 'speaking' || voice.error) return;
    const timer = window.setTimeout(() => setCaptionVisible(false), 3600);
    return () => window.clearTimeout(timer);
  }, [captionText, voice.phase, voice.error]);

  /* ---------- Réaction du dot à la parole réelle de l'utilisateur ---------- */

  useEffect(() => {
    const text = voice.pending;
    if (!text) {
      previousPendingRef.current = '';
      return;
    }
    const growth = text.length - previousPendingRef.current.length;
    previousPendingRef.current = text;
    if (growth > 0) pulse(Math.min(0.9, 0.26 + growth * 0.16));
  }, [voice.pending, pulse]);

  /* ---------- Envoi de texte depuis la barre du bas ---------- */

  const submitTyped = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const text = draft.trim();
      if (!text) return;
      prime();
      setDraft('');
      if (voice.active && voice.phase === 'listening') {
        voice.speak(text);
        return;
      }
      pendingTextRef.current = text;
      if (!voice.active) voice.activate();
    },
    [draft, prime, voice],
  );

  // Le texte tapé part dès que l'écoute est réellement armée.
  useEffect(() => {
    const queued = pendingTextRef.current;
    if (!queued || !voice.active || voice.phase !== 'listening') return;
    pendingTextRef.current = null;
    voice.speak(queued);
  }, [voice.active, voice.phase, voice.speak]);

  useEffect(() => {
    if (voice.error) pendingTextRef.current = null;
  }, [voice.error]);

  /* ---------- Navigation (menu discret, réglages, fermeture) ---------- */

  const closeMenu = useCallback((restoreFocus = true) => {
    setMenuOpen(false);
    if (restoreFocus) menuButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.querySelector<HTMLElement>('a, button')?.focus();
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMenu();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previous && previous.isConnected) previous.focus();
    };
  }, [menuOpen, closeMenu]);

  const handleDot = (): void => {
    prime();
    if (voice.active) voice.toggle();
    else voice.activate();
  };

  const closeScreen = (): void => {
    setMenuOpen(false);
    navigate({ name: 'home' });
  };

  const dotLabel = !voice.active
    ? 'Démarrer la conversation vocale'
    : voice.phase === 'speaking'
      ? 'Arrêter la réponse et couper le micro'
      : voice.phase === 'thinking'
        ? 'Annuler la réponse et couper le micro'
        : 'Couper le micro';


  return (
    <div
      className="voice-screen"
      data-phase={dotPhase}
      data-active={voice.active ? 'true' : 'false'}
      onPointerDown={prime}
    >
      {needsStart && !voice.active ? (
        <button
          type="button"
          className="vs-start"
          onClick={() => {
            prime();
            void voice.activate();
          }}
        >
          <span className="vs-start__title">Touchez pour parler</span>
          <span className="vs-start__hint">
            Le navigateur demande une action pour ouvrir le micro.
          </span>
        </button>
      ) : null}
      <header className="voice-screen__top">
        <button
          ref={menuButtonRef}
          type="button"
          className="vs-circle"
          aria-label="Ouvrir la navigation"
          aria-expanded={menuOpen}
          aria-controls="voice-menu"
          onClick={() => setMenuOpen((value) => !value)}
        >
          <Icon name="menu" size={20} />
        </button>

        <a className="vs-circle" href={href({ name: 'settings' })} aria-label="Ouvrir les réglages">
          <Icon name="settings" size={20} />
        </a>
      </header>

      <div className="voice-screen__stage">
        <button
          type="button"
          className="voice-screen__dot"
          onClick={handleDot}
          aria-label={dotLabel}
          aria-pressed={voice.active}
        >
          <KwesDroid phase={dotPhase} levelRef={levelRef} className="voice-screen__canvas" />
        </button>
      </div>

      <footer className="voice-screen__foot">
        <p
          id="voice-caption"
          className="vs-caption"
          data-visible={captionVisible && captionText ? 'true' : 'false'}
          data-tone={voice.error ? 'error' : 'neutral'}
          aria-hidden="true"
        >
          {captionText || '\u00A0'}
        </p>

        <div className="vs-bar">
          <form className="vs-ask" onSubmit={submitTyped} aria-label="Écrire à Kwes">
            <input
              className="vs-ask__input"
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Demander à Kwes"
              aria-label="Écrire un message à Kwes"
              enterKeyHint="send"
              autoComplete="off"
              spellCheck={false}
            />
          </form>

          <button
            type="button"
            className="vs-fab vs-fab--close"
            onClick={closeScreen}
            aria-label="Fermer et revenir à l’accueil"
          >
            <Icon name="cancel" size={21} />
          </button>
        </div>
      </footer>

      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {voiceAnnouncement(voice)}
      </p>
      {voice.error ? (
        <p className="sr-only" role="alert">
          {voice.error}
        </p>
      ) : null}

      {menuOpen ? (
        <div
          className="vs-menu"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeMenu();
          }}
        >
          <div
            id="voice-menu"
            ref={panelRef}
            className="vs-menu__panel"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
          >
            <p className="vs-menu__title">Aller à</p>
            {MENU.map((entry) => (
              <a
                key={entry.label}
                className="vs-menu__item"
                href={href(entry.route)}
                onClick={() => closeMenu(false)}
              >
                <Icon name={entry.icon} size={18} />
                {entry.label}
              </a>
            ))}
            <button type="button" className="vs-menu__close" onClick={() => closeMenu()}>
              Fermer
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
