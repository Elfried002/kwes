import { useEffect, useRef, useState } from 'react';
import { errorMessage, listTasks, sendChat } from '../lib/api';
import { clampProgress, formatRelative, greeting, truncate } from '../lib/format';
import { readDraft, usePreferences, writeDraft } from '../lib/prefs';
import { href, navigate } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { HybridOrb } from '../components/orb/HybridOrb';
import { OrbStatus } from '../components/OrbStatus';
import { Composer } from '../components/Composer';
import { StatusPill } from '../components/StatusPill';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import type { Task } from '../lib/types';

const ACTIVE_STATUSES = new Set(['queued', 'planning', 'running', 'awaiting_approval', 'paused']);

export function HomeScreen() {
  const {
    orbState,
    notifyChatStarted,
    notifyChatAnswered,
    notifyApiError,
    resetOrb,
    refreshKey,
    bumpRefresh,
    probeHealth,
    connection,
    serverStatus,
    setMicActive,
  } = useKwes();
  const prefs = usePreferences();
  const [draft, setDraft] = useState(() => readDraft('home'));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [tasksLoading, setTasksLoading] = useState(true);

  useEffect(() => {
    writeDraft('home', draft);
  }, [draft]);

  useEffect(() => {
    const controller = new AbortController();
    setTasksLoading(true);
    listTasks(controller.signal)
      .then((result) => {
        setTasks(result);
        setTasksError(null);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setTasksError(errorMessage(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setTasksLoading(false);
      });
    return () => controller.abort();
  }, [refreshKey]);

  const activeTasks = tasks
    .filter((task) => ACTIVE_STATUSES.has(task.status))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 4);

  const submit = async (): Promise<void> => {
    const message = draft.trim();
    if (!message || sending) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setSending(true);
    setError(null);
    notifyChatStarted();
    try {
      const result = await sendChat(
        { conversation_id: null, message, language: prefs.language, mode: 'auto' },
        controller.signal,
      );
      writeDraft('home', '');
      setDraft('');
      notifyChatAnswered();
      bumpRefresh();
      navigate({ name: 'chat', conversationId: result.conversation_id });
    } catch (cause) {
      if (controller.signal.aborted) {
        resetOrb();
        return;
      }
      setError(errorMessage(cause));
      notifyApiError(cause);
    } finally {
      setSending(false);
      abortRef.current = null;
      setMicActive(false);
    }
  };

  const liveUpdates = connection === 'online';

  return (
    <div className="page">
      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero__copy">
          <span className="page-head__eyebrow">
            {greeting()} ·{' '}
            {new Date().toLocaleDateString('fr-FR', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </span>
          <h1 id="home-title">Qu’est-ce qu’on fait aujourd’hui ?</h1>
          <p className="home-hero__lede">
            Dites-le avec vos mots. Kwes s’en occupe, vous montre où il en est, et vous demande votre
            accord dès qu’une action peut avoir des conséquences.
          </p>
          <div className="home-hero__actions">
            <a className="btn btn--primary" href={href({ name: 'chat' })}>
              <Icon name="chat" size={17} />
              Parler à Kwes
            </a>
            <a className="btn" href={href({ name: 'tasks' })}>
              <Icon name="activity" size={17} />
              Voir ce qu’il fait
            </a>
          </div>
        </div>

        <div className="orb-hero">
          <HybridOrb
            state={orbState}
            className="orb--hero"
            onActivate={() => navigate({ name: 'chat' })}
            label="Orb Kwes — ouvrir la conversation"
          />
          <OrbStatus showCaption />
        </div>
      </section>

      <div className="home-grid">
        <section className="card card--pad" aria-labelledby="quick-title">
          <div className="panel-title">
            <h2 id="quick-title">Demander à Kwes</h2>
          </div>

          {error ? (
            <p className="notice notice--danger" role="alert" style={{ marginBottom: 12 }}>
              {error} — votre brouillon est conservé sur cet appareil.
            </p>
          ) : null}

          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => {
              void submit();
            }}
            busy={sending}
            onStop={() => abortRef.current?.abort()}
            placeholder="Ex. : prépare un plan de lancement pour un service de veille concurrentielle"
            micAllowed={prefs.voiceEnabled}
            hint="Votre message part directement à Kwes · brouillon conservé en cas d’échec"
          />

          {!liveUpdates ? (
            <p className="notice notice--info" style={{ marginTop: 14 }}>
              <Icon name="alert" size={16} />
              <span>
                La liaison en direct est interrompue. Vous pouvez continuer à écrire : Kwes vous
                répondra, et son avancement se mettra à jour à chaque actualisation.
              </span>
            </p>
          ) : null}

          <div className="divider" />

          <div className="panel-title">
            <h3>Ce qu’il fait en ce moment</h3>
            <a className="meta" href={href({ name: 'tasks' })}>
              Tout voir
            </a>
          </div>

          {tasksLoading ? (
            <div className="stack stack--sm" aria-hidden="true">
              <div className="skeleton skeleton--row" />
              <div className="skeleton skeleton--row" />
            </div>
          ) : tasksError ? (
            <p className="notice notice--warning">
              <Icon name="alert" size={16} />
              <span>Impossible de charger son travail pour le moment : {tasksError}</span>
            </p>
          ) : activeTasks.length === 0 ? (
            <p className="muted" style={{ fontSize: '0.8125rem' }}>
              Kwes ne travaille sur rien pour le moment. Dites-lui ce que vous voulez accomplir.
            </p>
          ) : (
            <div className="mission-list">
              {activeTasks.map((task) => (
                <a key={task.id} className="mission" href={href({ name: 'task', id: task.id })}>
                  <div className="mission__top">
                    <span className="mission__title">{truncate(task.title, 64)}</span>
                    <StatusPill status={task.status} />
                  </div>
                  <div className="mission__meta">
                    <span>{formatRelative(task.updated_at)}</span>
                    <span>{clampProgress(task.progress)} % du travail</span>
                  </div>
                  <div className="progress" aria-hidden="true">
                    <div
                      className="progress__bar"
                      style={{ width: `${clampProgress(task.progress)}%` }}
                    />
                  </div>
                </a>
              ))}
            </div>
          )}
        </section>

        <aside className="stack">
          <section className="card card--pad" aria-labelledby="status-title">
            <div className="panel-title">
              <h2 id="status-title">Est-ce que tout va bien ?</h2>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => {
                  probeHealth();
                  bumpRefresh();
                }}
              >
                <Icon name="refresh" size={14} />
                Vérifier
              </button>
            </div>
            <div className="stack stack--sm" style={{ fontSize: '0.8125rem' }}>
              <div className="row row--between">
                <span className="muted">Kwes répond</span>
                <span
                  className={`badge badge--${serverStatus === 'ok' ? 'success' : serverStatus === 'unreachable' ? 'danger' : 'warning'}`}
                >
                  {serverStatus === 'ok'
                    ? 'Oui'
                    : serverStatus === 'degraded'
                      ? 'Lentement'
                      : serverStatus === 'unreachable'
                        ? 'Non'
                        : 'Je vérifie…'}
                </span>
              </div>
              <div className="row row--between">
                <span className="muted">Mises à jour en direct</span>
                <span
                  className={`badge badge--${liveUpdates ? 'success' : connection === 'offline' ? 'danger' : 'warning'}`}
                >
                  {liveUpdates ? 'Oui' : connection === 'offline' ? 'Non' : 'En attente'}
                </span>
              </div>
              <p className="meta" style={{ marginTop: 4 }}>
                {liveUpdates
                  ? 'Kwes vous montre son avancement au fur et à mesure.'
                  : 'L’avancement s’affichera à chaque actualisation de la page.'}
              </p>
            </div>
          </section>

          <section className="card card--pad" aria-labelledby="limits-title">
            <h2 id="limits-title" style={{ fontSize: '1rem', marginBottom: 8 }}>
              Ce que Kwes fait, et ce qu’il ne fait pas
            </h2>
            <ul
              className="stack stack--sm"
              style={{ listStyle: 'none', fontSize: '0.8125rem', color: 'var(--muted-strong)' }}
            >
              <li>· Vous écrivez, il répond et agit pour vous.</li>
              <li>· Vous voyez chaque étape de son travail.</li>
              <li>· Rien de délicat sans votre accord.</li>
              <li>· Aucun paiement, aucun appel, aucun accès à vos comptes.</li>
            </ul>
          </section>
        </aside>
      </div>

      {!tasksLoading && !tasksError && tasks.length === 0 ? (
        <div style={{ marginTop: 'var(--sp-5)' }}>
          <EmptyState
            title="Votre espace est prêt"
            icon={<Icon name="spark" size={26} />}
            action={
              <a className="btn btn--soft" href={href({ name: 'chat' })}>
                Parler à Kwes
              </a>
            }
          >
            Rien encore ici. Commencez par écrire à Kwes : tout ce qu’il fera apparaîtra dans votre
            espace.
          </EmptyState>
        </div>
      ) : null}
    </div>
  );
}
