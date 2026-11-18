import { useEffect, useState, type ReactNode } from 'react';
import { clearSession, useSession } from '../lib/auth';
import { firstName, initials } from '../lib/format';
import { href, type Route } from '../lib/router';
import { listApprovals } from '../lib/api';
import { useApi } from '../lib/hooks';
import { useKwes, type UiConnection } from '../state/KwesProvider';
import { BrandMark } from './BrandMark';
import { TenantSwitcher } from './TenantSwitcher';
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
// Trois espaces seulement : Accueil, Activité, Profil. Le vocal s'ouvre depuis
// l'accueil, les échanges et les accords sont rattachés à leur espace.
const NAV: NavEntry[] = [
  { label: 'Accueil', shortLabel: 'Accueil', route: { name: 'home' }, icon: 'home' },
  { label: 'Discussions', shortLabel: 'Discussions', route: { name: 'conversations' }, icon: 'history' },
  { label: 'Activité', shortLabel: 'Activité', route: { name: 'tasks' }, icon: 'activity' },
  { label: 'Profil', shortLabel: 'Profil', route: { name: 'settings' }, icon: 'settings' },
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
      // Le profil regroupe les réglages ; les accords restent liés à l'activité.
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
  const [drawer, setDrawer] = useState(false);

  // Le tiroir mobile se referme dès qu'on change d'écran ou avec Échap.
  useEffect(() => {
    setDrawer(false);
  }, [route]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') setDrawer(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawer]);

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

          <div className="rail__tenant">
            <TenantSwitcher compact />
          </div>

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
            <button
              type="button"
              className="mobile-bar__icon"
              aria-label={drawer ? 'Fermer le menu' : 'Ouvrir le menu'}
              aria-expanded={drawer}
              onClick={() => setDrawer((current) => !current)}
            >
              <Icon name="menu" size={20} />
            </button>
            <a className="brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
              <BrandMark size={26} state={orbState} />
              <span className="brand__name">Kwes</span>
            </a>
            <a
              className="mobile-bar__icon"
              href={href({ name: 'settings' })}
              aria-label="Votre profil"
            >
              <span className="mobile-bar__avatar" aria-hidden="true">
                {initials(session?.email || session?.userId || 'kwes')}
              </span>
            </a>
          </header>
          <main id="main" className="main" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>

      {drawer ? (
        <div className="drawer" role="dialog" aria-modal="true" aria-label="Menu">
          <button
            type="button"
            className="drawer__scrim"
            aria-label="Fermer le menu"
            onClick={() => setDrawer(false)}
          />
          <div className="drawer__panel">
            <div className="drawer__head">
              <a className="brand" href={href({ name: 'home' })} aria-label="Kwes — accueil">
                <BrandMark size={30} state={orbState} />
                <span className="brand__name">Kwes</span>
              </a>
              <button
                type="button"
                className="drawer__close"
                aria-label="Fermer"
                onClick={() => setDrawer(false)}
              >
                <Icon name="cancel" size={18} />
              </button>
            </div>

            <a className="drawer__new" href={href({ name: 'home' })}>
              <Icon name="edit" size={18} />
              Nouvelle demande
            </a>

            <div className="drawer__tenant">
              <TenantSwitcher />
            </div>

            <nav className="drawer__nav" aria-label="Sections">
              {NAV.map((entry) => (
                <a
                  key={entry.label}
                  className="drawer__item"
                  href={href(entry.route)}
                  aria-current={isActive(route, entry.route) ? 'page' : undefined}
                >
                  <Icon name={entry.icon} size={19} />
                  <span>{entry.label}</span>
                  {entry.route.name === 'approvals' && waiting > 0 ? (
                    <span className="drawer__count">{waiting}</span>
                  ) : null}
                </a>
              ))}
            </nav>

            <div className="drawer__foot">
              <ConnectionBadge />
              {session ? (
                <button type="button" className="drawer__logout" onClick={() => clearSession()}>
                  <Icon name="logout" size={17} />
                  Se déconnecter
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

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
