import { useCallback, useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../lib/api';

interface Scope {
  scope: string;
  usage: string;
  risk: string;
}

interface Capability {
  id: string;
  label: string;
  status: string;
}

interface Connection {
  id: string;
  status: string;
  account: string | null;
  last_error: string | null;
}

interface Connector {
  provider_id: string;
  display_name: string;
  category: string;
  auth_mode: string;
  status: string;
  capabilities: Capability[];
  scopes: Scope[];
  limits: string | null;
  docs_url: string | null;
  connection: Connection | null;
}

const STATUS_LABEL: Record<string, string> = {
  available: 'Disponible',
  needs_configuration: 'Configuration requise',
  provider_review: 'Validation du fournisseur en cours',
  unavailable: 'Indisponible',
};

const CONNECTION_LABEL: Record<string, string> = {
  active: 'Connecté',
  pending: 'En attente',
  expired: 'Expiré',
  error: 'Erreur',
  revoked: 'Déconnecté',
};

export function ConnectorsScreen() {
  const [items, setItems] = useState<Connector[]>([]);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [jeton, setJeton] = useState('');
  const [cible, setCible] = useState<string | null>(null);

  const charger = useCallback(async () => {
    try {
      const data = await apiRequest<{ items: Connector[] }>('/connectors');
      setItems(data.items);
      setErreur(null);
    } catch (cause) {
      setErreur(errorMessage(cause));
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  const connecter = async (provider: Connector) => {
    setAction(provider.provider_id);
    setErreur(null);
    try {
      if (provider.auth_mode === 'oauth2' || provider.auth_mode === 'oauth2_pkce') {
        const data = await apiRequest<{ authorize_url: string }>(
          `/connectors/${provider.provider_id}/connect`,
          { method: 'POST' },
        );
        window.location.assign(data.authorize_url);
        return;
      }
      setCible(provider.provider_id);
      setJeton('');
    } catch (cause) {
      setErreur(errorMessage(cause));
    } finally {
      setAction(null);
    }
  };

  const envoyerJeton = async () => {
    if (!cible || jeton.trim().length < 8) return;
    setAction(cible);
    try {
      await apiRequest(`/connectors/${cible}/token`, {
        method: 'POST',
        body: { token: jeton.trim() },
      });
      setCible(null);
      setJeton('');
      await charger();
    } catch (cause) {
      setErreur(errorMessage(cause));
    } finally {
      setAction(null);
    }
  };

  const tester = async (provider: string) => {
    setAction(provider);
    try {
      const data = await apiRequest<{ ok: boolean; reason: string }>(
        `/connectors/${provider}/test`,
        { method: 'POST' },
      );
      setErreur(data.ok ? null : `Test négatif : ${data.reason}`);
      await charger();
    } catch (cause) {
      setErreur(errorMessage(cause));
    } finally {
      setAction(null);
    }
  };

  const deconnecter = async (provider: string) => {
    setAction(provider);
    try {
      await apiRequest(`/connectors/${provider}`, { method: 'DELETE' });
      await charger();
    } catch (cause) {
      setErreur(errorMessage(cause));
    } finally {
      setAction(null);
    }
  };

  if (chargement) return <div className="page"><p className="muted">Chargement des connecteurs…</p></div>;

  return (
    <div className="page stack">
      <header>
        <h1 style={{ fontSize: '1.35rem' }}>Connecteurs</h1>
        <p className="muted" style={{ fontSize: '0.875rem' }}>
          KWES n’accède qu’aux services que vous autorisez, avec les permissions affichées.
          Vous pouvez déconnecter et supprimer l’accès à tout moment.
        </p>
      </header>

      {erreur ? (
        <p className="notice notice--danger" role="alert">{erreur}</p>
      ) : null}

      {items.map((item) => {
        const etat = item.connection?.status ?? null;
        return (
          <section key={item.provider_id} className="card stack" style={{ gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong>{item.display_name}</strong>
              <span className="muted" style={{ fontSize: '0.75rem' }}>
                {etat ? CONNECTION_LABEL[etat] ?? etat : STATUS_LABEL[item.status] ?? item.status}
              </span>
            </div>

            <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.8125rem' }}>
              {item.scopes.map((scope) => (
                <li key={scope.scope}>
                  <code style={{ fontSize: '0.75rem' }}>{scope.scope.split('/').pop()}</code> — {scope.usage}
                </li>
              ))}
            </ul>

            {item.limits ? (
              <p className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>{item.limits}</p>
            ) : null}

            {item.status === 'needs_configuration' ? (
              <p className="notice notice--warning" style={{ fontSize: '0.75rem' }}>
                Les identifiants serveur de ce fournisseur ne sont pas configurés. La connexion
                reste bloquée jusqu’à leur installation — rien n’est simulé.
              </p>
            ) : null}

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!etat || etat === 'revoked' || etat === 'expired' || etat === 'error' ? (
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={action === item.provider_id || item.status === 'needs_configuration'}
                  onClick={() => void connecter(item)}
                >
                  {action === item.provider_id ? 'Connexion…' : 'Connecter'}
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn"
                    disabled={action === item.provider_id}
                    onClick={() => void tester(item.provider_id)}
                  >
                    Tester
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={action === item.provider_id}
                    onClick={() => void deconnecter(item.provider_id)}
                  >
                    Déconnecter
                  </button>
                </>
              )}
              {item.docs_url ? (
                <a className="btn" href={item.docs_url} target="_blank" rel="noreferrer noopener">
                  Documentation
                </a>
              ) : null}
            </div>

            {cible === item.provider_id ? (
              <div className="stack" style={{ gap: 6 }}>
                <label htmlFor={`tk-${item.provider_id}`} style={{ fontSize: '0.8125rem' }}>
                  Jeton d’accès (stocké chiffré, jamais réaffiché)
                </label>
                <input
                  id={`tk-${item.provider_id}`}
                  type="password"
                  value={jeton}
                  onChange={(event) => setJeton(event.target.value)}
                  autoComplete="off"
                />
                <button type="button" className="btn btn--primary" onClick={() => void envoyerJeton()}>
                  Enregistrer
                </button>
              </div>
            ) : null}
          </section>
        );
      })}

      <section className="card stack" style={{ gap: 8 }}>
        <strong>WhatsApp</strong>
        <p className="muted" style={{ fontSize: '0.8125rem', margin: 0 }}>
          KWES utilise WhatsApp Business Platform (Cloud API), avec un compte professionnel
          validé par Meta. Un compte WhatsApp personnel ne peut pas être connecté : l’API
          officielle ne donne pas accès aux conversations privées.
        </p>
        <a className="btn" href="#/whatsapp">Comprendre et préparer WhatsApp</a>
      </section>
    </div>
  );
}
