import type { ReactNode } from 'react';
import { clearSession, useSession } from '../lib/auth';
import { initials } from '../lib/format';
import { href, type Route } from '../lib/router';
import { useKwes, type UiConnection } from '../state/KwesProvider';
import { Icon, type IconName } from './Icon';

interface NavEntry {
  label: string;
  shortLabel: string;
  route: Route;
  icon: IconName;
}

const NAV: NavEntry[] = [
  { label: 'Accueil', shortLabel: 'Accueil', route: { name: 'home' }, icon: 'home' },
  { label: 'Chat', shortLabel: 'Chat', route: { name: 'chat' }, icon: 'chat' },
  { label: 'Conversations', shortLabel: 'Historique', route: { name: 'conversations' }, icon: 'history' },
  { label: 'Activités', shortLabel: 'Activités', route: { name: 'tasks' }, icon: 'activity' },
  { label: 'Validations', shortLabel: 'Validation', route: { name: 'approvals' }, icon: 'shield' },
  { label: 'Réglages', shortLabel: 'Réglages', route: { name: 'settings' }, icon: 'settings' },
];

const MOBILE_NAV = [NAV[0], NAV[1], NAV[3], NAV[4], NAV[5]].filter((entry): entry is NavEntry => Boolean(entry));

function isActive(route: Route, target: Route): boolean {
  switch (target.name) {
    case 'home':
      return route.name === 'home';
    case 'chat':
      return route.name === 'chat';
    case 'conversations':
      return route.name === 'conversations';
    case 'tasks':
      return route.name === 'tasks' || route.name === 'task';
    case 'approvals':
      return route.name === 'approvals';
    case 'settings':
      return route.name === 'settings';
    default:
      return false;
  }
}

const CONNECTION_LABELS: Record<UiConnection, string> = {
  idle: 'Non connecté',
  connecting: 'Connexion…',
  online: 'Connecté',
  reconnecting: 'Reconnexion…',
  offline: 'Hors ligne',
  unauthorized: 'Session expirée',
};

function connectionClass(connection: UiConnection): string {
  if (connection === 'online') return 'online';
  if (connection === 'connecting' || connection === 'reconnecting') return 'reconnecting';
  if (connection === 'offline' || connection === 'unauthorized') return 'offline';
  return 'idle';
}

export function ConnectionBadge({ compact = false }: { compact?: boolean }) {
  const { connection, reconnectAttempt, serverStatus } = useKwes();
  const label = CONNECTION_LABELS[connection];
  const detail =
    connection === 'offline' && reconnectAttempt > 0
      ? `Tentative ${reconnectAttempt} · reconnexion automatique`
      : serverStatus === 'degraded'
        ? 'Un service backend est dégradé'
        : serverStatus === 'unreachable'
          ? 'API health injoignable'
          : undefined;

  return (
    <div className="connection" data-status={connectionClass(connection)} title={detail ?? label}>
      <span className="connection__dot" aria-hidden="true" />
      <span aria-live="polite">{compact && connection === 'online' ? 'En ligne' : label}</span>
    </div>
  );
}

export function AppShell({ children, route }: { children: ReactNode; route: Route }) {
  const session = useSession();
  const { orbMeta, lastError, clearError } = useKwes();

  return (
    <>
      <a className="skip-link" href="#main">
        Aller au contenu principal
      </a>

      <div className="app-shell">
        <aside className="sidebar" aria-label="Navigation principale">
          <a className="brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
            <img className="brand__mark" src="/brand/Kwes_Favicon_192.png" alt="" width={38} height={38} />
            <span>
              <span className="brand__name">Kwes</span>
              <span className="brand__tag">Personal AI Agent</span>
            </span>
          </a>

          <nav className="nav" aria-label="Sections">
            <span className="nav__label">Espace de travail</span>
            {NAV.map((entry) => (
              <a
                key={entry.label}
                className="nav__item"
                href={href(entry.route)}
                aria-current={isActive(route, entry.route) ? 'page' : undefined}
              >
                <Icon name={entry.icon} size={18} className="nav__icon" />
                {entry.label}
              </a>
            ))}
          </nav>

          <div className="sidebar__foot">
            <ConnectionBadge />
            {session ? (
              <div className="user-chip">
                <span className="user-chip__avatar" aria-hidden="true">
                  {initials(session.email)}
                </span>
                <span className="user-chip__mail" title={session.email || session.userId}>
                  {session.email || session.userId || 'Session dev'}
                </span>
                <button
                  type="button"
                  className="btn btn--icon"
                  aria-label="Se déconnecter"
                  title="Se déconnecter"
                  onClick={() => {
                    clearSession();
                  }}
                >
                  <Icon name="logout" size={17} />
                </button>
              </div>
            ) : null}
          </div>
        </aside>

        <div>
          <header className="mobile-bar">
            <a className="brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
              <img className="brand__mark" src="/brand/Kwes_Favicon_192.png" alt="" width={30} height={30} />
              <span className="brand__name">Kwes</span>
            </a>
            <div className="mobile-bar__status">
              <ConnectionBadge compact />
            </div>
          </header>
          <main id="main" className="main" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>

      <nav className="bottom-nav" aria-label="Navigation mobile">
        {MOBILE_NAV.map((entry) => (
          <a
            key={entry.label}
            className="bottom-nav__item"
            href={href(entry.route)}
            aria-current={isActive(route, entry.route) ? 'page' : undefined}
          >
            <Icon name={entry.icon} size={20} />
            {entry.shortLabel}
          </a>
        ))}
      </nav>

      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {`Kwes : ${orbMeta.announcement}`}
      </p>

      {lastError ? (
        <div className="toast toast--danger" role="alert">
          <Icon name="alert" size={18} />
          <span>{lastError}</span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={clearError} aria-label="Fermer l’alerte">
            <Icon name="cancel" size={14} />
          </button>
        </div>
      ) : null}
    </>
  );
}
