import { useEffect, useId, useRef, useState } from 'react';
import { Icon } from './Icon';

/**
 * Bouton « Installer l'application » (PWA, sans Capacitor).
 *
 * - Chromium / Edge / Samsung : `beforeinstallprompt` est capturé, le bouton
 *   déclenche l'invite native ; après `appinstalled`, il disparaît.
 * - iOS / iPadOS : pas d'événement, on affiche l'aide en deux étapes
 *   (« Partager » puis « Sur l'écran d'accueil »).
 * - Application déjà ouverte en mode installé : rien n'est affiché.
 */

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

type InstallState = 'checking' | 'ready' | 'ios' | 'installed' | 'unsupported';

function readStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  const iosStandalone = (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia('(display-mode: standalone)').matches;
}

function readIos(): boolean {
  if (typeof navigator === 'undefined') return false;
  const agent = navigator.userAgent;
  const iPadAsMac = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  return /iPad|iPhone|iPod/.test(agent) || iPadAsMac;
}

export function InstallApp({
  variant = 'soft',
  size,
  className,
  showInstalledNote = false,
  showUnsupportedNote = false,
  label = 'Installer l’application',
}: {
  variant?: 'primary' | 'soft' | 'ghost';
  size?: 'sm';
  className?: string;
  showInstalledNote?: boolean;
  showUnsupportedNote?: boolean;
  label?: string;
}) {
  const [state, setState] = useState<InstallState>('checking');
  const [helpOpen, setHelpOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const promptRef = useRef<InstallPromptEvent | null>(null);
  const helpId = useId();

  useEffect(() => {
    if (readStandalone()) {
      setState('installed');
      return;
    }

    const onPrompt = (event: Event): void => {
      event.preventDefault();
      promptRef.current = event as InstallPromptEvent;
      setState('ready');
    };
    const onInstalled = (): void => {
      promptRef.current = null;
      setState('installed');
    };

    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);

    // Sur iOS l'invite n'existe pas : l'aide manuelle est la seule voie.
    setState(readIos() ? 'ios' : 'unsupported');

    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const install = async (): Promise<void> => {
    const prompt = promptRef.current;
    if (!prompt) {
      if (readIos()) setHelpOpen((open) => !open);
      return;
    }
    setBusy(true);
    try {
      await prompt.prompt();
      const choice = await prompt.userChoice;
      promptRef.current = null;
      if (choice.outcome === 'accepted') {
        setState('installed');
      } else {
        // Refus explicite : on ne réaffiche pas l'invite pendant cette visite.
        setState('unsupported');
      }
    } catch {
      /* L'invite a déjà été consommée : le bouton retombe sur son état normal. */
    } finally {
      setBusy(false);
    }
  };

  if (state === 'checking') return null;

  if (state === 'installed') {
    return showInstalledNote ? (
      <p className="install__done">
        <Icon name="check" size={15} />
        Kwes est installé sur cet appareil.
      </p>
    ) : null;
  }

  if (state === 'unsupported') {
    return showUnsupportedNote ? (
      <p className="install__note">
        <Icon name="alert" size={15} />
        Ce navigateur ne propose pas encore l’installation. Sur iPhone ou iPad, utilisez
        « Partager » puis « Sur l’écran d’accueil ».
      </p>
    ) : null;
  }

  const buttonClass = ['btn', `btn--${variant}`, size === 'sm' ? 'btn--sm' : '', 'install__btn']
    .filter(Boolean)
    .join(' ');

  return (
    <span className={`install ${className ?? ''}`}>
      <button
        type="button"
        className={buttonClass}
        onClick={() => void install()}
        disabled={busy}
        aria-expanded={state === 'ios' ? helpOpen : undefined}
        aria-controls={state === 'ios' ? helpId : undefined}
      >
        <Icon name="install" size={16} />
        {busy ? 'Ouverture…' : label}
      </button>

      {state === 'ios' ? (
        <span className={`install__help ${helpOpen ? 'is-open' : ''}`} id={helpId}>
          <span className="install__step">
            <span className="install__num" aria-hidden="true">
              1
            </span>
            <span>
              Touchez <strong>Partager</strong> <Icon name="share" size={13} /> dans la barre de Safari.
            </span>
          </span>
          <span className="install__step">
            <span className="install__num" aria-hidden="true">
              2
            </span>
            <span>
              Choisissez <strong>Sur l’écran d’accueil</strong>, puis <strong>Ajouter</strong>.
            </span>
          </span>
        </span>
      ) : null}
    </span>
  );
}
