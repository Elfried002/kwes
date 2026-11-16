import type { ReactNode } from 'react';
import { clearSession, useSession } from '../lib/auth';
import { initials } from '../lib/format';
import { href, type Route } from '../lib/router';
import { listApprovals } from '../lib/api';
import { useApi } from '../lib/hooks';
import { useKwes, type UiConnection } from '../state/KwesProvider';
import { BrandMark } from './BrandMark';
import { Icon, type IconName } from './Icon';

interface NavEntry {
  label: string;
  shortLabel: string;
  route: Route;
  icon: IconName;
}

/**
 * Cinq entrées, en français courant. Aucun terme interne (mission, tâche,
 * validation, activité, conversation) : l'utilisateur voit ce que Kwes fait,
 * pas comment il est construit.
 */
const NAV: NavEntry[] = [
  { label: 'Accueil', shortLabel: 'Accueil', route: { name: 'home' }, icon: 'home' },
  { label: 'Parler', shortLabel: 'Parler', route: { name: 'chat' }, icon: 'chat' },
  { label: 'Ce qu’il fait', shortLabel: 'Travail', route: { name: 'tasks' }, icon: 'activity' },
  {
    label: 'Il attend votre accord',
    shortLabel: 'Accord',
    route: { name: 'approvals' },
    icon: 'shield',
  },
  { label: 'Réglages', shortLabel: 'Réglages', route: { name: 'settings' }, icon: 'settings' },
];

function isActive(route: Route, target: Route): boolean {
  switch (target.name) {
    case 'home':
      return route.name === 'home';
    case 'chat':
      return route.name === 'chat';
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
      ? 'Kwes essaie de se reconnecter tout seul.'
      : serverStatus === 'degraded'
        ? 'Un service de Kwes répond lentement en ce moment.'
        : serverStatus === 'unreachable'
          ? 'Kwes ne répond pas pour le moment.'
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
  const { orbState, orbMeta, lastError, clearError, refreshKey } = useKwes();
  const approvals = useApi((signal) => listApprovals(signal), [], { refreshKey });
  const waiting = (approvals.data ?? []).filter((approval) => approval.status === 'pending').length;

  return (
    <>
      <a className="skip-link" href="#main">
        Aller au contenu principal
      </a>

      <div className="app-shell">
        <aside className="sidebar" aria-label="Navigation principale">
          <a className="brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
            <BrandMark size={38} state={orbState} />
            <span>
              <span className="brand__name">Kwes</span>
              <span className="brand__tag">Assistant personnel</span>
            </span>
          </a>

          <nav className="nav" aria-label="Sections">
            <span className="nav__label">Votre espace</span>
            {NAV.map((entry) => (
              <a
                key={entry.label}
                className="nav__item"
                href={href(entry.route)}
                aria-current={isActive(route, entry.route) ? 'page' : undefined}
              >
                <Icon name={entry.icon} size={18} className="nav__icon" />
                {entry.label}
                {entry.route.name === 'approvals' && waiting > 0 ? (
                  <span className="nav__count" aria-label={`${waiting} demande(s) en attente`}>
                    {waiting}
                  </span>
                ) : null}
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
              <BrandMark size={30} state={orbState} />
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
        {NAV.map((entry) => (
          <a
            key={entry.label}
            className="bottom-nav__item"
            href={href(entry.route)}
            aria-current={isActive(route, entry.route) ? 'page' : undefined}
          >
            <Icon name={entry.icon} size={20} />
            {entry.shortLabel}
            {entry.route.name === 'approvals' && waiting > 0 ? (
              <span className="bottom-nav__dot" aria-hidden="true" />
            ) : null}
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
