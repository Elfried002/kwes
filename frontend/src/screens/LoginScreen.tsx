import { useState } from 'react';
import { API_BASE_URL, errorMessage, isApiError, requestDevToken } from '../lib/api';
import { saveSession } from '../lib/auth';
import { navigate } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { HybridOrb } from '../components/orb/HybridOrb';
import { Icon } from '../components/Icon';

export function LoginScreen() {
  const { orbState, serverStatus } = useKwes();
  const [email, setEmail] = useState(() => {
    try {
      return localStorage.getItem('kwes.dev.email') ?? '';
    } catch {
      return '';
    }
  });
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState<'dev' | 'token' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [devUnavailable, setDevUnavailable] = useState(false);
  const [showTokenForm, setShowTokenForm] = useState(false);

  const completeLogin = (rawToken: string): void => {
    const result = saveSession(rawToken);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    try {
      if (email) localStorage.setItem('kwes.dev.email', email);
    } catch {
      /* ignore */
    }
    navigate({ name: 'home' }, { replace: true });
  };

  const handleDevLogin = async (): Promise<void> => {
    const clean = email.trim();
    if (!clean || !clean.includes('@')) {
      setError('Saisissez une adresse e-mail valide (elle identifie votre profil de démonstration).');
      return;
    }
    setBusy('dev');
    setError(null);
    try {
      const devToken = await requestDevToken(clean);
      completeLogin(devToken);
    } catch (cause) {
      if (isApiError(cause) && (cause.status === 404 || cause.status === 405 || cause.status === 501)) {
        setDevUnavailable(true);
        setShowTokenForm(true);
        setError(
          "L'endpoint de démonstration /dev/token n'est pas exposé par ce backend. Collez un JWT signé côté serveur pour continuer.",
        );
      } else {
        setError(errorMessage(cause));
      }
    } finally {
      setBusy(null);
    }
  };

  const handleTokenLogin = (): void => {
    setError(null);
    completeLogin(token);
  };

  return (
    <div className="login">
      <section className="login__pitch" aria-labelledby="login-title">
        <div className="login__orb">
          <HybridOrb state={orbState} className="orb--compact" />
        </div>
        <span className="login__tag">
          <Icon name="spark" size={13} />
          Alpha · environnement de démonstration
        </span>
        <h1 id="login-title">Votre intelligence. Vos actions. Votre monde.</h1>
        <p>
          Kwes converse, planifie et exécute des missions avec des outils réels et limités. Chaque
          action sensible passe par votre validation. L’état de l’Orb reflète uniquement des
          événements serveur, jamais le texte du modèle.
        </p>
        <p className="meta">
          Backend : {serverStatus === 'ok' ? 'joignable' : serverStatus === 'degraded' ? 'dégradé' : serverStatus === 'unreachable' ? 'injoignable' : 'vérification…'}
          {' · '}
          {API_BASE_URL}
        </p>
      </section>

      <section className="login__form" aria-label="Connexion">
        <div className="login__form-inner">
          <div>
            <h2 style={{ fontSize: '1.35rem' }}>Entrer dans votre espace</h2>
            <p className="muted" style={{ fontSize: '0.8125rem', marginTop: 6 }}>
              Authentification par jeton JWT. Aucune clé secrète n’est stockée ni manipulée dans le navigateur.
            </p>
          </div>

          {error ? (
            <p className="notice notice--danger" role="alert">
              {error}
            </p>
          ) : null}

          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void handleDevLogin();
            }}
          >
            <div className="field">
              <label className="field__label" htmlFor="login-email">
                Adresse e-mail
              </label>
              <input
                id="login-email"
                className="input"
                type="email"
                name="email"
                autoComplete="email"
                inputMode="email"
                placeholder="vous@exemple.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <span className="field__hint">
                En développement, le backend peut délivrer un JWT de démo pour cet e-mail.
              </span>
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={busy !== null}>
              {busy === 'dev' ? 'Connexion…' : 'Obtenir un jeton de démo'}
            </button>
          </form>

          {devUnavailable ? (
            <p className="notice notice--warning">
              Le backend actuel n’expose pas <code className="mono">POST /dev/token</code>. Utilisez le
              jeton fourni par l’équipe (signé avec <code className="mono">DEV_JWT_SECRET</code> côté serveur).
            </p>
          ) : null}

          <details className="disclosure" open={showTokenForm}>
            <summary>J’ai déjà un jeton JWT</summary>
            <div className="stack">
              <div className="field">
                <label className="field__label" htmlFor="login-token">
                  Jeton JWT
                </label>
                <textarea
                  id="login-token"
                  className="textarea"
                  rows={4}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                />
                <span className="field__hint">
                  Collé depuis un émetteur de confiance. Le jeton reste dans ce navigateur
                  (localStorage) et expire selon son claim <code className="mono">exp</code>.
                </span>
              </div>
              <button
                type="button"
                className="btn btn--soft"
                onClick={handleTokenLogin}
                disabled={token.trim().length === 0 || busy !== null}
              >
                Se connecter avec ce jeton
              </button>
            </div>
          </details>

          <p className="login__foot">
            PWA installable · Aucun secret dans le bundle · Les données de démonstration sont
            marquées <strong>[DEMO]</strong>.
          </p>
        </div>
      </section>
    </div>
  );
}
