import { useState } from 'react';
import { API_BASE_URL, errorMessage, isApiError, listIntegrations } from '../lib/api';
import { signOut, useSession } from '../lib/auth';
import { formatDateTime } from '../lib/format';
import { useApi } from '../lib/hooks';
import { updatePreferences, usePreferences, type Preferences } from '../lib/prefs';
import { useKwes } from '../state/KwesProvider';
import { buildWsUrl } from '../lib/ws';
import { ConnectionBadge } from '../components/AppShell';
import { Icon } from '../components/Icon';
import { InstallApp } from '../components/InstallApp';

function Switch({
  checked,
  onChange,
  labelId,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  labelId: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelId}
      className="switch"
      onClick={() => onChange(!checked)}
      disabled={disabled}
    />
  );
}

export function SettingsScreen() {
  const session = useSession();
  const prefs = usePreferences();
  const { health } = useKwes();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const integrations = useApi((signal) => listIntegrations(signal), []);

  const setPreference = <K extends keyof Preferences>(key: K, value: Preferences[K]): void => {
    updatePreferences({ [key]: value } as Partial<Preferences>);
    setNotice('C’est enregistré sur cet appareil.');
    setError(null);
  };

  const toggleNotifications = async (next: boolean): Promise<void> => {
    setError(null);
    if (!next) {
      setPreference('notificationsEnabled', false);
      return;
    }
    if (!('Notification' in window)) {
      setError('Ce navigateur ne propose pas les notifications.');
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      if (permission === 'granted') {
        setPreference('notificationsEnabled', true);
        setNotice('Notifications autorisées. Kwes n’envoie que de vraies nouvelles.');
      } else {
        setError('Vous avez refusé les notifications. Vous pouvez changer d’avis dans les réglages du navigateur.');
      }
    } catch {
      setError('Impossible de demander l’autorisation pour les notifications.');
    }
  };

  const clearDrafts = (): void => {
    let removed = 0;
    try {
      const keys: string[] = [];
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (key && key.startsWith('kwes.draft.')) keys.push(key);
      }
      for (const key of keys) {
        localStorage.removeItem(key);
        removed += 1;
      }
      setNotice(
        removed === 0 ? 'Aucun brouillon à supprimer.' : `${removed} brouillon(s) supprimé(s).`,
      );
    } catch {
      setError('Le stockage de ce navigateur est inaccessible.');
    }
  };

  const wsEndpoint = buildWsUrl('•••').replace('token=%E2%80%A2%E2%80%A2%E2%80%A2', 'session=<session>');
  const dependencies = health?.dependencies ? Object.entries(health.dependencies) : [];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Compte</span>
          <h1>Réglages</h1>
          <p>Votre compte, vos préférences et l’application.</p>
        </div>
        <ConnectionBadge />
      </div>

      {notice ? (
        <p className="notice notice--success" role="status" style={{ marginBottom: 14 }}>
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="notice notice--danger" role="alert" style={{ marginBottom: 14 }}>
          {error}
        </p>
      ) : null}

      <div className="settings-grid">
        <section className="card card--pad" aria-labelledby="install-title">
          <div className="panel-title">
            <h2 id="install-title">Installer l’application</h2>
          </div>
          <p className="muted" style={{ fontSize: '0.8125rem' }}>
            Kwes s’installe comme une application : une icône sur votre écran d’accueil, un écran
            plein, et l’ouverture plus rapide. Aucun magasin d’applications n’est nécessaire.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <InstallApp variant="primary" showInstalledNote showUnsupportedNote />
          </div>
          <p className="meta" style={{ marginTop: 10 }}>
            Sur ordinateur, l’installation se propose dans la barre d’adresse du navigateur.
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="profile-title">
          <div className="panel-title">
            <h2 id="profile-title">Profil</h2>
            <span className="badge">Lecture seule</span>
          </div>
          <dl className="kv">
            <dt>E-mail</dt>
            <dd>{session?.email || '—'}</dd>
            <dt>Connexion valable jusqu’au</dt>
            <dd>
              {session?.expiresAt
                ? formatDateTime(new Date(session.expiresAt * 1000).toISOString())
                : 'non communiquée'}
            </dd>
            <dt>Langue</dt>
            <dd>
              <label className="sr-only" htmlFor="settings-language">
                Langue de l’interface et des messages
              </label>
              <select
                id="settings-language"
                className="select"
                value={prefs.language}
                onChange={(event) => setPreference('language', event.target.value === 'en' ? 'en' : 'fr')}
              >
                <option value="fr">Français</option>
                <option value="en">English</option>
              </select>
            </dd>
          </dl>
          <p className="meta" style={{ marginTop: 10 }}>
            La modification du profil arrivera plus tard. Rien n’est simulé ici.
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="history-title">
          <div className="panel-title">
            <h2 id="history-title">Vos échanges</h2>
          </div>
          <p className="muted" style={{ fontSize: '0.8125rem' }}>
            Retrouvez une conversation passée et reprenez-la là où vous l’avez laissée.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <a className="btn" href="#/conversations">
              <Icon name="history" size={15} />
              Voir mes échanges
            </a>
          </div>
        </section>

        <section className="card card--pad" aria-labelledby="voice-title">
          <div className="panel-title">
            <h2 id="voice-title">Voix et notifications</h2>
          </div>

          <div className="setting">
            <div className="setting__text">
              <strong id="voice-label">Voix et dictée</strong>
              <span>Affiche le bouton micro pour dicter vos messages au lieu de les écrire.</span>
            </div>
            <Switch
              checked={prefs.voiceEnabled}
              onChange={(next) => setPreference('voiceEnabled', next)}
              labelId="voice-label"
            />
          </div>

          <div className="setting">
            <div className="setting__text">
              <strong id="notif-label">Notifications</strong>
              <span>
                Le navigateur demandera votre accord au moment de l’activation. Kwes n’envoie que de
                vraies nouvelles.
              </span>
            </div>
            <Switch
              checked={prefs.notificationsEnabled}
              onChange={(next) => void toggleNotifications(next)}
              labelId="notif-label"
            />
          </div>

          <p className="notice notice--info" style={{ marginTop: 14 }}>
            <Icon name="alert" size={16} />
            <span>
              La lecture à voix haute n’est pas encore disponible : Kwes ne joue aucun son qui ne
              serait pas réellement produit.
            </span>
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="integrations-title">
          <div className="panel-title">
            <h2 id="integrations-title">Connexions</h2>
            <span className="badge">Lecture seule</span>
          </div>

          {integrations.loading && !integrations.data ? (
            <div className="skeleton skeleton--row" aria-hidden="true" />
          ) : integrations.error ? (
            <p className="notice notice--warning">
              <Icon name="alert" size={16} />
              <span>
                {isApiError(integrations.error) && integrations.error.status === 404
                  ? 'Aucune connexion n’est encore proposée sur ce projet.'
                  : `Impossible de lister vos connexions : ${errorMessage(integrations.error)}`}
              </span>
            </p>
          ) : (integrations.data ?? []).length === 0 ? (
            <p className="muted" style={{ fontSize: '0.8125rem' }}>
              Aucune connexion ajoutée pour le moment. Les services que Kwes pourra utiliser
              apparaîtront ici.
            </p>
          ) : (
            <div className="list">
              {(integrations.data ?? []).map((integration) => (
                <div className="list__row" key={integration.id}>
                  <div className="list__main">
                    <span className="list__title">{integration.provider}</span>
                    <div className="list__meta">
                      <span className="badge">{integration.status}</span>
                      {integration.scopes?.length ? <span>{integration.scopes.join(', ')}</span> : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card card--pad" aria-labelledby="privacy-title">
          <div className="panel-title">
            <h2 id="privacy-title">Confidentialité</h2>
          </div>
          <p className="muted" style={{ fontSize: '0.8125rem' }}>
            Vos brouillons restent dans ce navigateur. Vos échanges sont conservés sur votre compte,
            pour la durée prévue par le service. Kwes ne montre jamais son raisonnement interne :
            seulement ce qu’il a prévu, fait et obtenu.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <button type="button" className="btn" onClick={clearDrafts}>
              <Icon name="trash" size={15} />
              Supprimer les brouillons de cet appareil
            </button>
          </div>
        </section>

        <section className="card card--pad" aria-labelledby="security-title">
          <div className="panel-title">
            <h2 id="security-title">Sécurité</h2>
          </div>
          <p className="muted" style={{ fontSize: '0.8125rem' }}>
            Votre connexion est gérée par Supabase Auth. Votre mot de passe ne passe jamais par
            Kwes. La déconnexion coupe l’accès immédiatement.
          </p>
          <button
            type="button"
            className="btn btn--danger"
            style={{ marginTop: 12 }}
            onClick={() => {
              void signOut();
            }}
          >
            <Icon name="logout" size={15} />
            Se déconnecter
          </button>

          <details className="disclosure" style={{ marginTop: 16 }}>
            <summary>Avancé</summary>
            <dl className="kv">
              <dt>Service</dt>
              <dd className="mono">{API_BASE_URL}</dd>
              <dt>Flux temps réel</dt>
              <dd className="mono">{wsEndpoint}</dd>
              <dt>Compte</dt>
              <dd className="mono">{session?.userId || '—'}</dd>
              <dt>Version du service</dt>
              <dd className="mono">{health?.version ?? '—'}</dd>
              <dt>Authentification</dt>
              <dd>Supabase Auth — aucune clé fournisseur côté navigateur</dd>
              {dependencies.map(([name, value]) => (
                <div key={name} style={{ display: 'contents' }}>
                  <dt>Dépendance {name}</dt>
                  <dd className="mono">{value ?? '—'}</dd>
                </div>
              ))}
            </dl>
            {integrations.error ? (
              <p className="meta" style={{ marginTop: 8 }}>
                Erreur des connexions : {errorMessage(integrations.error)}
              </p>
            ) : null}
          </details>
        </section>
      </div>

      <p className="meta" style={{ marginTop: 'var(--sp-5)' }}>
        Kwes · votre assistant personnel.
      </p>
    </div>
  );
}
