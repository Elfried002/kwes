import { useEffect, useRef, useState } from 'react';
import {
  API_BASE_URL,
  errorMessage,
  isApiError,
  listIntegrations,
  listVoices,
  synthesizeSpeech,
  type VoiceOption,
} from '../lib/api';
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

/** Phrase courte lue par la prévisualisation : utile, jamais un texte de démo. */
const VOICE_PREVIEW_TEXT = 'Bonjour, c’est Kwes. Voilà comment je sonne quand je vous parle.';

function genderLabel(gender: string | null): string {
  if (gender === 'male') return 'voix masculine';
  if (gender === 'female') return 'voix féminine';
  if (gender === 'neutral') return 'voix neutre';
  return '';
}

function languageLabel(language: string | null): string {
  if (!language) return '';
  if (language === 'fr') return 'français';
  if (language === 'en') return 'anglais';
  if (language === 'es') return 'espagnol';
  if (language === 'de') return 'allemand';
  return language;
}

/** Résumé lisible d'une voix : langue, accent, timbre. */
function voiceSummary(voice: VoiceOption): string {
  const parts = [
    languageLabel(voice.language),
    voice.accent ? `accent ${voice.accent}` : '',
    genderLabel(voice.gender),
    voice.description ?? '',
  ].filter(Boolean);
  return parts.join(' · ');
}

export function SettingsScreen() {
  const session = useSession();
  const prefs = usePreferences();
  const { health } = useKwes();
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const integrations = useApi((signal) => listIntegrations(signal), []);
  const voices = useApi((signal) => listVoices(signal), []);

  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const [previewingId, setPreviewingId] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      const audio = previewAudioRef.current;
      if (audio) {
        audio.onended = null;
        audio.onerror = null;
        audio.pause();
      }
      previewAudioRef.current = null;
    };
  }, []);

  /** Prévisualisation réelle : même route que la conversation vocale. */
  const previewVoice = async (voiceId: string | null): Promise<void> => {
    if (previewingId) return;
    setPreviewError(null);
    setPreviewingId(voiceId ?? '__default__');
    try {
      const speech = await synthesizeSpeech(VOICE_PREVIEW_TEXT, undefined, voiceId);
      // Repli : le service premium peut être indisponible (quota, panne).
      // On prononce alors l'extrait avec la voix de l'appareil pour que
      // l'utilisateur entende quand même une voix, sans mensonge sur la source.
      if (!speech.audioBase64) {
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(VOICE_PREVIEW_TEXT);
          utterance.lang = 'fr-FR';
          const french = window.speechSynthesis
            .getVoices()
            .find((voice) => voice.lang?.toLowerCase().startsWith('fr'));
          if (french) utterance.voice = french;
          utterance.onend = () => setPreviewingId(null);
          utterance.onerror = () => setPreviewingId(null);
          setPreviewError(
            'Voix de votre appareil : le service premium est indisponible pour le moment.',
          );
          window.speechSynthesis.speak(utterance);
          return;
        }
        setPreviewingId(null);
        setPreviewError(
          speech.reason
            ? `Aucun extrait audio : ${speech.reason}`
            : 'Le service vocal n’a renvoyé aucun audio.',
        );
        return;
      }
      const previous = previewAudioRef.current;
      if (previous) {
        previous.onended = null;
        previous.onerror = null;
        previous.pause();
      }
      const audio = new Audio(
        `data:${speech.mimeType ?? 'audio/mpeg'};base64,${speech.audioBase64}`,
      );
      previewAudioRef.current = audio;
      const done = (message?: string): void => {
        setPreviewingId(null);
        if (message) setPreviewError(message);
      };
      audio.onended = () => done();
      audio.onerror = () => done('Extrait audio illisible par ce navigateur.');
      await audio.play().catch(() => {
        done('Lecture bloquée par le navigateur : cliquez à nouveau sur « Écouter ».');
      });
    } catch (cause) {
      setPreviewingId(null);
      setPreviewError(`Prévisualisation impossible : ${errorMessage(cause)}`);
    }
  };

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

  const voiceOptions = voices.data?.voices ?? [];
  const storedVoiceMissing =
    prefs.voiceId !== null &&
    voiceOptions.length > 0 &&
    !voiceOptions.some((option) => option.id === prefs.voiceId);
  const selectedVoice = voiceOptions.find((option) => option.id === prefs.voiceId) ?? null;

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
              Kwes ne joue que ce que le service vocal renvoie réellement. Si l’audio est
              indisponible, la réponse reste affichée en texte — rien n’est simulé.
            </span>
          </p>
        </section>

        <section className="card card--pad" aria-labelledby="voice-picker-title">
          <div className="panel-title">
            <h2 id="voice-picker-title">La voix de Kwes</h2>
            {voiceOptions.length > 0 ? (
              <span className="badge">
                {voiceOptions.length} voix
              </span>
            ) : null}
          </div>

          {voices.loading && !voices.data ? (
            <div className="skeleton skeleton--row" aria-hidden="true" />
          ) : voices.error ? (
            <p className="notice notice--warning">
              <Icon name="alert" size={16} />
              <span>Impossible de lister les voix : {errorMessage(voices.error)}</span>
            </p>
          ) : voiceOptions.length === 0 ? (
            <p className="muted" style={{ fontSize: '0.8125rem' }}>
              Aucune voix n’est proposée pour le moment.{' '}
              {voices.data?.reason ?? 'Le service vocal n’est pas configuré côté serveur.'}
            </p>
          ) : (
            <>
              <p className="muted" style={{ fontSize: '0.8125rem' }}>
                Choisissez la voix qui vous parle. Le réglage est conservé sur cet appareil et
                s’applique dès le prochain échange vocal.
              </p>

              <div className="row" style={{ marginTop: 12, flexWrap: 'wrap', gap: 10 }}>
                <label className="sr-only" htmlFor="settings-voice">
                  Voix utilisée quand Kwes parle
                </label>
                <select
                  id="settings-voice"
                  className="select"
                  value={prefs.voiceId ?? ''}
                  onChange={(event) => {
                    const value = event.target.value;
                    setPreference('voiceId', value ? value : null);
                    setPreviewError(null);
                  }}
                >
                  <option value="">Voix par défaut de Kwes</option>
                  {storedVoiceMissing && prefs.voiceId ? (
                    <option value={prefs.voiceId}>
                      {prefs.voiceId} (voix enregistrée, indisponible)
                    </option>
                  ) : null}
                  {voiceOptions.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.name}
                    </option>
                  ))}
                </select>

                <button
                  type="button"
                  className="btn"
                  onClick={() => void previewVoice(prefs.voiceId)}
                  disabled={previewingId !== null}
                >
                  <Icon name={previewingId ? 'activity' : 'mic'} size={15} />
                  {previewingId ? 'Lecture…' : 'Écouter'}
                </button>
              </div>

              <p className="meta" style={{ marginTop: 10 }}>
                {selectedVoice
                  ? `${selectedVoice.name} — ${voiceSummary(selectedVoice) || 'voix ElevenLabs'}.`
                  : 'Voix par défaut du service vocal.'}
              </p>

              {previewError ? (
                <p className="notice notice--danger" role="alert" style={{ marginTop: 10 }}>
                  <Icon name="alert" size={16} />
                  <span>{previewError}</span>
                </p>
              ) : null}

              {voices.data?.mock ? (
                <p className="meta" style={{ marginTop: 8 }}>
                  Le service vocal n’est pas configuré : aucun extrait ne peut être écouté.
                </p>
              ) : null}
            </>
          )}
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
