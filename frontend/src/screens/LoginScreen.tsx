import { useEffect, useState, type KeyboardEvent } from 'react';
import { clearSession, completePasswordRecovery } from '../lib/auth';
import { authErrorMessage, passwordScore, validatePassword } from '../lib/auth-errors';
import { supabase, supabaseConfigured, SUPABASE_CONFIG_ERROR } from '../lib/supabase';
import { useKwes } from '../state/KwesProvider';
import { HybridOrb } from '../components/orb/HybridOrb';
import { Icon } from '../components/Icon';
import type { AuthMode } from '../lib/router';

type Mode = AuthMode;

/** État du fournisseur Google, détecté sans redirection ni blocage de l'écran. */
type GoogleState = 'unknown' | 'available' | 'unavailable';

function redirectTo(): string {
  return `${window.location.origin}/`;
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true" focusable="false">
      <path
        fill="#4285F4"
        d="M23.5 12.3c0-.8-.07-1.6-.2-2.3H12v4.4h6.4a5.5 5.5 0 0 1-2.4 3.6v3h3.9c2.2-2.1 3.6-5.1 3.6-8.7z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3c-1.1.7-2.4 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.4v3.1A12 12 0 0 0 12 24z"
      />
      <path fill="#FBBC05" d="M5.4 14.4a7.2 7.2 0 0 1 0-4.6V6.7H1.4a12 12 0 0 0 0 10.6l4-2.9z" />
      <path
        fill="#EA4335"
        d="M12 4.8c1.7 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.4 6.7l4 3.1C6.3 6.9 8.9 4.8 12 4.8z"
      />
    </svg>
  );
}

function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  autoComplete: string;
  hint?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <div className="field__with-action">
        <input
          id={id}
          className="input"
          type={visible ? 'text' : 'password'}
          name={id}
          autoComplete={autoComplete}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required
        />
        <button
          type="button"
          className="field__action"
          aria-pressed={visible}
          aria-label={visible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? 'Masquer' : 'Afficher'}
        </button>
      </div>
      {hint ? <span className="field__hint">{hint}</span> : null}
    </div>
  );
}

const SCORE_LABELS = ['Très faible', 'Faible', 'Moyen', 'Bon', 'Excellent'];

export function LoginScreen({ initialMode = 'signin' }: { initialMode?: Mode }) {
  const { orbState, serverStatus } = useKwes();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState<'email' | 'google' | 'reset' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [googleState, setGoogleState] = useState<GoogleState>('unknown');

  /*
   * Détection non bloquante : l'URL d'autorisation Google est demandée à Supabase,
   * puis sondée sans suivre la redirection. Un 4xx signifie que le fournisseur
   * n'est pas encore activé ; un cas indéterminé laisse le bouton actif.
   */
  useEffect(() => {
    if (!supabaseConfigured) return;
    let cancelled = false;
    void supabase.auth
      .signInWithOAuth({ provider: 'google', options: { redirectTo: redirectTo(), skipBrowserRedirect: true } })
      .then(async ({ data, error: failure }) => {
        if (cancelled || failure || !data?.url) return;
        try {
          const probe = await fetch(data.url, {
            method: 'GET',
            redirect: 'manual',
            cache: 'no-store',
            signal: AbortSignal.timeout(4000),
          });
          if (cancelled) return;
          if (probe.type === 'opaqueredirect' || probe.status === 0) {
            setGoogleState('available');
          } else if (probe.status >= 400) {
            setGoogleState('unavailable');
          }
        } catch {
          /* Sonde impossible (CORS, délai) : on ne conclut pas. */
        }
      })
      .catch(() => {
        /* Réseau indisponible : le bouton reste actif et l'erreur s'affichera au clic. */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const resetFeedback = (): void => {
    setError(null);
    setInfo(null);
  };

  const switchMode = (next: Mode): void => {
    resetFeedback();
    setMode(next);
    if (next !== 'signup') setConfirm('');
    // L'URL suit l'onglet sans déclencher de navigation ni perdre la saisie.
    const path =
      next === 'signup' ? '#/inscription' : next === 'reset' ? '#/mot-de-passe-oublie' : '#/connexion';
    try {
      window.history.replaceState(null, '', path);
    } catch {
      /* history indisponible : l'onglet reste fonctionnel */
    }
  };

  const requireConfig = (): boolean => {
    if (supabaseConfigured) return false;
    setError(SUPABASE_CONFIG_ERROR);
    return true;
  };

  const handleSignIn = async (): Promise<void> => {
    resetFeedback();
    if (requireConfig()) return;
    const clean = email.trim();
    if (!clean.includes('@')) {
      setError('Saisissez une adresse e-mail valide.');
      return;
    }
    if (!password) {
      setError('Saisissez votre mot de passe.');
      return;
    }
    setBusy('email');
    try {
      const { error: failure } = await supabase.auth.signInWithPassword({ email: clean, password });
      if (failure) {
        setError(authErrorMessage(failure));
        return;
      }
      // Session publiée par onAuthStateChange : App ouvre l'espace de travail.
    } catch (cause) {
      setError(authErrorMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const handleSignUp = async (): Promise<void> => {
    resetFeedback();
    if (requireConfig()) return;
    const clean = email.trim();
    if (!clean.includes('@')) {
      setError('Saisissez une adresse e-mail valide.');
      return;
    }
    const weakness = validatePassword(password, clean);
    if (weakness) {
      setError(weakness);
      return;
    }
    if (password !== confirm) {
      setError('Les deux mots de passe ne correspondent pas.');
      return;
    }
    setBusy('email');
    try {
      const { data, error: failure } = await supabase.auth.signUp({
        email: clean,
        password,
        options: { emailRedirectTo: redirectTo() },
      });
      if (failure) {
        setError(authErrorMessage(failure));
        return;
      }
      if (data.session) return;
      if (data.user && (data.user.identities?.length ?? 0) === 0) {
        setError(
          'Un compte existe déjà avec cette adresse e-mail. Connectez-vous ou réinitialisez votre mot de passe.',
        );
        return;
      }
      setInfo(
        `Compte créé. Un e-mail de confirmation a été envoyé à ${clean} : ouvrez le lien qu’il contient, puis revenez vous connecter.`,
      );
      setPassword('');
      setConfirm('');
      setMode('signin');
    } catch (cause) {
      setError(authErrorMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const handleGoogle = async (): Promise<void> => {
    resetFeedback();
    if (requireConfig()) return;
    setBusy('google');
    try {
      const { data, error: failure } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: redirectTo(), skipBrowserRedirect: true },
      });
      if (failure) {
        setError(authErrorMessage(failure));
        return;
      }
      const url = data?.url;
      if (!url) {
        setError('La connexion Google n’a pas pu être initialisée. Réessayez dans un instant.');
        return;
      }
      /*
       * Sonde non bloquante : si le fournisseur n'est pas activé côté Supabase,
       * l'URL renvoie un 400 JSON. On affiche alors un message français dans
       * l'écran plutôt que d'envoyer l'utilisateur sur une page d'erreur brute.
       */
      try {
        const probe = await fetch(url, {
          method: 'GET',
          redirect: 'manual',
          cache: 'no-store',
          signal: AbortSignal.timeout(4000),
        });
        if (probe.status >= 400) {
          let payload: Record<string, unknown> | null = null;
          try {
            payload = (await probe.json()) as Record<string, unknown>;
          } catch {
            payload = null;
          }
          const serverMessage = typeof payload?.msg === 'string' ? payload.msg : '';
          setGoogleState('unavailable');
          setError(
            authErrorMessage({
              status: probe.status,
              message: serverMessage,
              code: /provider is not enabled|unsupported provider/i.test(serverMessage)
                ? 'provider_disabled'
                : undefined,
            }),
          );
          return;
        }
      } catch {
        /* Sonde impossible (CORS, délai) : on laisse la redirection standard décider. */
      }
      window.location.assign(url);
    } catch (cause) {
      setError(authErrorMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const handleReset = async (): Promise<void> => {
    resetFeedback();
    if (requireConfig()) return;
    const clean = email.trim();
    if (!clean.includes('@')) {
      setError('Saisissez l’adresse e-mail de votre compte.');
      return;
    }
    setBusy('reset');
    try {
      const { error: failure } = await supabase.auth.resetPasswordForEmail(clean, {
        redirectTo: redirectTo(),
      });
      if (failure) {
        setError(authErrorMessage(failure));
        return;
      }
      setInfo(
        `Si un compte existe pour ${clean}, un e-mail de réinitialisation vient d’être envoyé. Le lien expire au bout d’une heure.`,
      );
    } catch (cause) {
      setError(authErrorMessage(cause));
    } finally {
      setBusy(null);
    }
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    switchMode(mode === 'signin' ? 'signup' : 'signin');
  };

  const score = passwordScore(password);
  const scoreLabel = SCORE_LABELS[score] ?? 'Faible';

  return (
    <div className="login">
      <section className="login__pitch" aria-labelledby="login-title">
        <div className="login__orb">
          <HybridOrb state={orbState} className="orb--compact" />
        </div>
        <span className="login__tag">
          <Icon name="shield" size={13} />
          Connexion sécurisée
        </span>
        <h1 id="login-title">Votre intelligence. Vos actions. Votre monde.</h1>
        <p>
          Kwes converse, planifie et exécute des missions avec des outils volontairement limités.
          Chaque action sensible attend votre validation. L’Orb reflète l’état réel de l’agent, jamais
          le texte du modèle.
        </p>
        <ul className="login__trust">
          <li>
            <Icon name="check" size={14} />
            Chiffrement en transit
          </li>
          <li>
            <Icon name="check" size={14} />
            Aucun secret dans le navigateur
          </li>
          <li>
            <Icon name="check" size={14} />
            Service{' '}
            {serverStatus === 'ok'
              ? 'opérationnel'
              : serverStatus === 'degraded'
                ? 'dégradé'
                : serverStatus === 'unreachable'
                  ? 'injoignable'
                  : 'en vérification'}
          </li>
        </ul>
      </section>

      <section className="login__form" aria-label="Authentification">
        <div className="login__form-inner">
          <div>
            <h2 style={{ fontSize: '1.35rem' }}>
              {mode === 'reset'
                ? 'Mot de passe oublié'
                : mode === 'signup'
                  ? 'Créer votre compte'
                  : 'Entrer dans votre espace'}
            </h2>
            <p className="muted" style={{ fontSize: '0.8125rem', marginTop: 6 }}>
              {mode === 'reset'
                ? 'Indiquez l’adresse e-mail de votre compte : nous vous envoyons un lien sécurisé pour choisir un nouveau mot de passe.'
                : mode === 'signup'
                  ? 'Quelques secondes suffisent. Vos identifiants sont gérés par notre fournisseur d’authentification, jamais par l’agent.'
                  : 'Connectez-vous pour retrouver vos conversations, vos missions et vos validations.'}
            </p>
          </div>

          {!supabaseConfigured ? (
            <p className="notice notice--warning" role="status">
              <Icon name="alert" size={16} />
              <span>{SUPABASE_CONFIG_ERROR}</span>
            </p>
          ) : null}

          {error ? (
            <p className="notice notice--danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{error}</span>
            </p>
          ) : null}

          {info ? (
            <p className="notice notice--success" role="status">
              <Icon name="check" size={16} />
              <span>{info}</span>
            </p>
          ) : null}

          {mode === 'reset' ? null : (
            <div className="login__tabs" role="tablist" aria-label="Se connecter ou créer un compte">
              <button
                type="button"
                role="tab"
                id="tab-signin"
                aria-selected={mode === 'signin'}
                aria-controls="panel-signin"
                tabIndex={mode === 'signin' ? 0 : -1}
                className="login__tab"
                onClick={() => switchMode('signin')}
                onKeyDown={onTabKeyDown}
              >
                Se connecter
              </button>
              <button
                type="button"
                role="tab"
                id="tab-signup"
                aria-selected={mode === 'signup'}
                aria-controls="panel-signup"
                tabIndex={mode === 'signup' ? 0 : -1}
                className="login__tab"
                onClick={() => switchMode('signup')}
                onKeyDown={onTabKeyDown}
              >
                Créer un compte
              </button>
            </div>
          )}

          {mode === 'signin' ? (
            <form
              className="stack"
              id="panel-signin"
              role="tabpanel"
              aria-labelledby="tab-signin"
              onSubmit={(event) => {
                event.preventDefault();
                void handleSignIn();
              }}
            >
              <div className="field">
                <label className="field__label" htmlFor="signin-email">
                  Adresse e-mail
                </label>
                <input
                  id="signin-email"
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
              </div>

              <PasswordField
                id="signin-password"
                label="Mot de passe"
                value={password}
                onChange={setPassword}
                autoComplete="current-password"
              />

              <div className="login__row">
                <button
                  type="button"
                  className="link-button"
                  onClick={() => switchMode('reset')}
                  disabled={busy !== null}
                >
                  Mot de passe oublié ?
                </button>
              </div>

              <button
                type="submit"
                className="btn btn--primary btn--block"
                disabled={busy !== null || !supabaseConfigured}
              >
                {busy === 'email' ? 'Connexion…' : 'Se connecter'}
              </button>
            </form>
          ) : null}

          {mode === 'signup' ? (
            <form
              className="stack"
              id="panel-signup"
              role="tabpanel"
              aria-labelledby="tab-signup"
              onSubmit={(event) => {
                event.preventDefault();
                void handleSignUp();
              }}
            >
              <div className="field">
                <label className="field__label" htmlFor="signup-email">
                  Adresse e-mail
                </label>
                <input
                  id="signup-email"
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
              </div>

              <div>
                <PasswordField
                  id="signup-password"
                  label="Mot de passe"
                  value={password}
                  onChange={setPassword}
                  autoComplete="new-password"
                  hint="8 caractères minimum, avec au moins une lettre et un chiffre."
                />
                {password ? (
                  <div className="pw-meter" data-score={score} aria-hidden="true">
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                ) : null}
                {password ? (
                  <p className="field__hint" aria-live="polite">
                    Robustesse : {scoreLabel}
                  </p>
                ) : null}
              </div>

              <PasswordField
                id="signup-confirm"
                label="Confirmer le mot de passe"
                value={confirm}
                onChange={setConfirm}
                autoComplete="new-password"
                hint={
                  confirm && confirm !== password
                    ? 'Les deux saisies diffèrent pour l’instant.'
                    : undefined
                }
              />

              <button
                type="submit"
                className="btn btn--primary btn--block"
                disabled={busy !== null || !supabaseConfigured}
              >
                {busy === 'email' ? 'Création…' : 'Créer mon compte'}
              </button>
            </form>
          ) : null}

          {mode === 'reset' ? (
            <form
              className="stack"
              onSubmit={(event) => {
                event.preventDefault();
                void handleReset();
              }}
            >
              <div className="field">
                <label className="field__label" htmlFor="reset-email">
                  Adresse e-mail du compte
                </label>
                <input
                  id="reset-email"
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
              </div>
              <button
                type="submit"
                className="btn btn--primary btn--block"
                disabled={busy !== null || !supabaseConfigured}
              >
                {busy === 'reset' ? 'Envoi…' : 'Envoyer le lien de réinitialisation'}
              </button>
              <button type="button" className="link-button" onClick={() => switchMode('signin')}>
                Retour à la connexion
              </button>
            </form>
          ) : null}

          {mode === 'reset' ? null : (
            <>
              <div className="login__divider">
                <span>ou</span>
              </div>
              <div className="login__google-block">
                <button
                  type="button"
                  className="btn btn--soft btn--block login__google"
                  onClick={() => void handleGoogle()}
                  disabled={busy !== null || !supabaseConfigured || googleState === 'unavailable'}
                  aria-describedby={googleState === 'unavailable' ? 'google-status' : undefined}
                >
                  <GoogleMark />
                  {busy === 'google' ? 'Redirection…' : 'Continuer avec Google'}
                  {googleState === 'unavailable' ? (
                    <span className="badge badge--soon">Bientôt disponible</span>
                  ) : null}
                </button>
                {googleState === 'unavailable' ? (
                  <p className="field__hint" id="google-status">
                    La connexion Google n’est pas encore activée. Créez votre compte avec une adresse
                    e-mail : l’accès Google sera proposé dès son ouverture.
                  </p>
                ) : null}
              </div>
            </>
          )}

          <p className="login__foot">
            Authentification assurée par Supabase. Votre mot de passe ne transite jamais par l’agent
            et n’est jamais stocké dans cette interface. Vous pouvez fermer votre session à tout
            moment depuis l’espace de travail.
          </p>
        </div>
      </section>
    </div>
  );
}

/** Affiché quand un lien de réinitialisation a ouvert une session de récupération. */
export function PasswordRecoveryScreen() {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setError(null);
    const weakness = validatePassword(password);
    if (weakness) {
      setError(weakness);
      return;
    }
    if (password !== confirm) {
      setError('Les deux mots de passe ne correspondent pas.');
      return;
    }
    setBusy(true);
    try {
      const { error: failure } = await supabase.auth.updateUser({ password });
      if (failure) {
        setError(authErrorMessage(failure));
        return;
      }
      setPassword('');
      setConfirm('');
      completePasswordRecovery();
    } catch (cause) {
      setError(authErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login login--single">
      <section className="login__form" aria-label="Nouveau mot de passe">
        <div className="login__form-inner">
          <div>
            <h1 style={{ fontSize: '1.5rem' }}>Choisir un nouveau mot de passe</h1>
            <p className="muted" style={{ fontSize: '0.8125rem', marginTop: 6 }}>
              Votre lien de réinitialisation est valide. Définissez un mot de passe que vous
              n’utilisez nulle part ailleurs.
            </p>
          </div>

          {error ? (
            <p className="notice notice--danger" role="alert">
              <Icon name="alert" size={16} />
              <span>{error}</span>
            </p>
          ) : null}

          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <PasswordField
              id="recovery-password"
              label="Nouveau mot de passe"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              hint="8 caractères minimum, avec au moins une lettre et un chiffre."
            />
            <PasswordField
              id="recovery-confirm"
              label="Confirmer le mot de passe"
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
            />
            <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
              {busy ? 'Enregistrement…' : 'Enregistrer et continuer'}
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                completePasswordRecovery();
                clearSession();
              }}
            >
              Annuler et se déconnecter
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
