import { useState } from 'react';
import { API_BASE_URL, errorMessage, isApiError, listIntegrations } from '../lib/api';
import { signOut, useSession } from '../lib/auth';
import { formatDateTime } from '../lib/format';
import { useApi } from '../lib/hooks';
import { updatePreferences, usePreferences, type Preferences } from '../lib/prefs';
import { buildWsUrl } from '../lib/ws';
import { ConnectionBadge } from '../components/AppShell';
import { Icon } from '../components/Icon';

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
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const integrations = useApi((signal) => listIntegrations(signal), []);

  const setPreference = <K extends keyof Preferences>(key: K, value: Preferences[K]): void => {
    updatePreferences({ [key]: value } as Partial<Preferences>);
    setNotice('Préférence enregistrée localement.');
    setError(null);
  };

  const toggleNotifications = async (next: boolean): Promise<void> => {
    setError(null);
    if (!next) {
      setPreference('notificationsEnabled', false);
      return;
    }
    if (!('Notification' in window)) {
      setError('Les notifications ne sont pas prises en charge par ce navigateur.');
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      if (permission === 'granted') {
        setPreference('notificationsEnabled', true);
        setNotice('Notifications navigateur autorisées. Kwes n’en envoie que si le backend en produit.');
      } else {
        setError('Permission de notification refusée par le navigateur.');
      }
    } catch {
      setError('Impossible de demander la permission de notification.');
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
      setNotice(`${removed} brouillon(s) local(aux) supprimé(s).`);
    } catch {
      setError('Le stockage local est inaccessible dans ce contexte.');
    }
  };

  const wsEndpoint = buildWsUrl('•••').replace('token=%E2%80%A2%E2%80%A2%E2%80%A2', 'session=<session>');

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Compte</span>
          <h1>Réglages</h1>
          <p>Préférences locales et état réel des intégrations exposées par l’API.</p>
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
        <section className="card card--pad" aria-labelledby="profile-title">
          <div className="panel-title">
            <h2 id="profile-title">Profil</h2>
            <span className="badge">Lecture seule</span>
          </div>
          <dl className="kv">
            <dt>E-mail</dt>
            <dd>{session?.email || '—'}</dd>
            <dt>Identifiant</dt>
            <dd className="mono">{session?.userId || '—'}</dd>
            <dt>Session expire</dt>
            <dd>
              {session?.expiresAt
                ? formatDateTime(new Date(session.expiresAt * 1000).toISOString())
                : 'non communiquée'}
            </dd>
            <dt>Langue</dt>
            <dd>
              <label className="sr-only" htmlFor="settings-language">
                Langue de l’interface et des requêtes
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
            L’édition du profil sera exposée par une route dédiée ; aucune écriture simulée n’est faite ici.
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="voice-title">
          <div className="panel-title">
            <h2 id="voice-title">Voix et notifications</h2>
          </div>

          <div className="setting">
            <div className="setting__text">
              <strong id="voice-label">Voix et dictée</strong>
              <span>
                Active le bouton micro (dictée navigateur, après autorisation explicite) et prépare la
                lecture audio.
              </span>
            </div>
            <Switch
              checked={prefs.voiceEnabled}
              onChange={(next) => setPreference('voiceEnabled', next)}
              labelId="voice-label"
            />
          </div>

          <div className="setting">
            <div className="setting__text">
              <strong id="notif-label">Notifications navigateur</strong>
              <span>
                La permission n’est demandée qu’à l’activation. Aucune notification n’est générée
                localement : elles proviennent des événements serveur.
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
              La synthèse vocale ElevenLabs n’est pas encore exposée par une route de l’API :
              aucun son n’est simulé et l’Orb ne passe en « Parle » qu’à la lecture d’un audio réel.
            </span>
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="integrations-title">
          <div className="panel-title">
            <h2 id="integrations-title">Intégrations</h2>
            <span className="badge">Lecture seule</span>
          </div>

          {integrations.loading && !integrations.data ? (
            <div className="skeleton skeleton--row" aria-hidden="true" />
          ) : integrations.error ? (
            <p className="notice notice--warning">
              <Icon name="alert" size={16} />
              <span>
                {isApiError(integrations.error) && integrations.error.status === 404
                  ? 'L’API n’expose pas encore de route /integrations (contrat P0). Aucune intégration ne peut être affichée ni connectée depuis cette interface.'
                  : `Intégrations indisponibles : ${errorMessage(integrations.error)}`}
              </span>
            </p>
          ) : (integrations.data ?? []).length === 0 ? (
            <p className="muted" style={{ fontSize: '0.8125rem' }}>
              Aucune intégration connectée. Les fournisseurs et périmètres (scopes) seront affichés ici
              lorsqu’ils existeront côté serveur.
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
            Les brouillons et préférences restent dans ce navigateur (localStorage). Les conversations
            et missions résident sur votre backend et suivent sa politique de rétention. Aucune trace de
            raisonnement privée n’est affichée : seuls le plan, les actions et leurs résultats le sont.
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <button type="button" className="btn" onClick={clearDrafts}>
              <Icon name="trash" size={15} />
              Supprimer les brouillons locaux
            </button>
          </div>
        </section>

        <section className="card card--pad" aria-labelledby="security-title">
          <div className="panel-title">
            <h2 id="security-title">Sécurité</h2>
          </div>
          <dl className="kv">
            <dt>API REST</dt>
            <dd className="mono">{API_BASE_URL}</dd>
            <dt>WebSocket</dt>
            <dd className="mono">{wsEndpoint}</dd>
            <dt>Authentification</dt>
            <dd>Supabase Auth — jamais de clé fournisseur côté client</dd>
          </dl>
          <p className="meta" style={{ marginTop: 10 }}>
            Votre session est gérée par Supabase Auth dans ce navigateur et présentée à chaque
            requête privée. La déconnexion la révoque immédiatement.
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
        </section>
      </div>

      <p className="meta" style={{ marginTop: 'var(--sp-5)' }}>
        Kwes · agent personnel autonome · Orb piloté par une machine à états déterministe.
      </p>
    </div>
  );
}
