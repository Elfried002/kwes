import type { ReactNode } from 'react';
import { clearSession, useSession } from '../lib/auth';
import { firstName, initials } from '../lib/format';
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
 * Le rail garde les écrans réels de l'utilisateur — ce que Kwes fait, ce qu'il
 * attend, les échanges passés — mais en icônes seules. Les libellés
 * n'apparaissent qu'au survol ou au clavier.
 */
const NAV: NavEntry[] = [
  { label: 'Accueil', shortLabel: 'Accueil', route: { name: 'home' }, icon: 'home' },
  { label: 'Parler', shortLabel: 'Parler', route: { name: 'voice' }, icon: 'mic' },
  { label: 'Vos échanges', shortLabel: 'Échanges', route: { name: 'conversations' }, icon: 'history' },
  { label: 'Ce qu’il fait', shortLabel: 'Travail', route: { name: 'tasks' }, icon: 'activity' },
  {
    label: 'Accord en attente',
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
    case 'voice':
      return route.name === 'voice';
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
  const profileName =
    firstName(session?.email, session?.displayName) || session?.email || session?.userId || 'Votre profil';

  return (
    <>
      <a className="skip-link" href="#main">
        Aller au contenu principal
      </a>

      <div className="app-shell">
        <aside className="rail" aria-label="Navigation principale">
          <a className="rail__brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
            <BrandMark size={34} state={orbState} />
            <span className="rail__label rail__wordmark">Kwes</span>
          </a>

          <a
            className="rail__new"
            href={href({ name: 'home' })}
            aria-label="Nouvelle demande"
            title="Nouvelle demande"
          >
            <Icon name="edit" size={20} />
            <span className="rail__label">Nouvelle demande</span>
          </a>

          <nav className="rail__nav" aria-label="Sections">
            {NAV.map((entry) => (
              <a
                key={entry.label}
                className="rail__item"
                href={href(entry.route)}
                aria-label={entry.label}
                title={entry.label}
                aria-current={isActive(route, entry.route) ? 'page' : undefined}
              >
                <Icon name={entry.icon} size={20} className="rail__icon" />
                <span className="rail__label">{entry.label}</span>
                {entry.route.name === 'approvals' && waiting > 0 ? (
                  <span className="rail__count" aria-label={`${waiting} demande(s) en attente`}>
                    {waiting}
                  </span>
                ) : null}
              </a>
            ))}
          </nav>

          <div className="rail__foot">
            <div className="rail__status">
              <ConnectionBadge />
            </div>
            {session ? (
              <div className="rail__account">
                <a
                  className="rail__user"
                  href={href({ name: 'settings' })}
                  aria-label={`${profileName} — réglages`}
                  title="Votre profil et les réglages"
                >
                  <span className="rail__avatar" aria-hidden="true">
                    {initials(session.email || session.userId || 'kwes')}
                  </span>
                  <span className="rail__label rail__user-name">{profileName}</span>
                </a>
                <button
                  type="button"
                  className="rail__logout"
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

        <div className="app-shell__body">
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
