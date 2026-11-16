import { useState } from 'react';
import {
  cancelTask,
  errorMessage,
  getTask,
  pauseTask,
  resumeTask,
} from '../lib/api';
import { clampProgress, formatDateTime, formatTime } from '../lib/format';
import { useApi } from '../lib/hooks';
import { href } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Icon } from '../components/Icon';
import { StatusPill, StepPill } from '../components/StatusPill';
import type { TaskStatus } from '../lib/types';

function summarize(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value.length > 900 ? `${value.slice(0, 900)}…` : value;
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 900 ? `${text.slice(0, 900)}…` : text;
  } catch {
    return null;
  }
}

const TERMINAL: TaskStatus[] = ['completed', 'failed', 'cancelled'];

export function TaskDetailScreen({ id }: { id: string }) {
  const { refreshKey, bumpRefresh, taskEvents } = useKwes();
  const { data: task, error, loading, reload } = useApi((signal) => getTask(id, signal), [id], {
    refreshKey,
  });
  const [action, setAction] = useState<'pause' | 'resume' | 'cancel' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const runAction = async (kind: 'pause' | 'resume' | 'cancel'): Promise<void> => {
    if (!task) return;
    setAction(kind);
    setActionError(null);
    try {
      if (kind === 'pause') await pauseTask(task.id);
      else if (kind === 'resume') await resumeTask(task.id);
      else await cancelTask(task.id);
      setConfirmCancel(false);
      reload();
      bumpRefresh();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setAction(null);
    }
  };

  if (loading && !task) {
    return (
      <div className="page">
        <div className="skeleton skeleton--block" aria-hidden="true" />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="page">
        <div className="page-head">
          <div>
            <a className="meta" href={href({ name: 'tasks' })}>
              ← Toutes les missions
            </a>
            <h1>Mission indisponible</h1>
          </div>
        </div>
        <p className="notice notice--warning" role="alert">
          <Icon name="alert" size={16} />
          <span>{errorMessage(error)}</span>
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <button type="button" className="btn" onClick={reload}>
            <Icon name="refresh" size={16} />
            Réessayer
          </button>
          <a className="btn btn--ghost" href={href({ name: 'tasks' })}>
            Retour aux activités
          </a>
        </div>
      </div>
    );
  }

  const progress = clampProgress(task.progress);
  const events = taskEvents(task.id).slice(0, 25);
  const canCancel = !TERMINAL.includes(task.status);
  const steps = task.steps ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <a className="meta" href={href({ name: 'tasks' })}>
            ← Toutes les missions
          </a>
          <h1 style={{ marginTop: 6, fontSize: '1.85rem' }}>{task.title}</h1>
          <div className="row" style={{ marginTop: 8 }}>
            <StatusPill status={task.status} />
            {task.priority ? <span className="badge">Priorité {task.priority}</span> : null}
            {task.conversation_id ? (
              <a className="btn btn--ghost btn--sm" href={href({ name: 'chat', conversationId: task.conversation_id })}>
                <Icon name="chat" size={14} />
                Conversation liée
              </a>
            ) : null}
            {task.status === 'awaiting_approval' ? (
              <a className="btn btn--soft btn--sm" href={href({ name: 'approvals' })}>
                <Icon name="shield" size={14} />
                Ouvrir les validations
              </a>
            ) : null}
          </div>
        </div>
        <div className="row">
          {task.status === 'running' ? (
            <button
              type="button"
              className="btn"
              onClick={() => void runAction('pause')}
              disabled={action !== null}
            >
              <Icon name="pause" size={15} />
              {action === 'pause' ? 'Pause…' : 'Mettre en pause'}
            </button>
          ) : null}
          {task.status === 'paused' ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => void runAction('resume')}
              disabled={action !== null}
            >
              <Icon name="play" size={15} />
              {action === 'resume' ? 'Reprise…' : 'Reprendre'}
            </button>
          ) : null}
          {canCancel ? (
            <button
              type="button"
              className="btn btn--danger"
              onClick={() => setConfirmCancel(true)}
              disabled={action !== null}
            >
              <Icon name="cancel" size={15} />
              Annuler la mission
            </button>
          ) : null}
        </div>
      </div>

      {actionError ? (
        <p className="notice notice--danger" role="alert" style={{ marginBottom: 14 }}>
          {actionError} — l’état affiché reste celui confirmé par le serveur.
        </p>
      ) : null}

      <div className="detail-grid">
        <div className="stack">
          <section className="card card--pad" aria-labelledby="progress-title">
            <div className="panel-title">
              <h2 id="progress-title">Progression</h2>
              <span className="meta">{progress} %</span>
            </div>
            <div
              className="progress"
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Progression de la mission"
            >
              <div
                className={`progress__bar ${task.status === 'completed' ? 'progress__bar--success' : task.status === 'failed' ? 'progress__bar--danger' : task.status === 'awaiting_approval' ? 'progress__bar--warning' : ''}`}
                style={{ width: `${progress}%` }}
              />
            </div>

            {task.error_code ? (
              <p className="notice notice--danger" style={{ marginTop: 14 }}>
                <Icon name="alert" size={16} />
                <span>
                  Échec signalé par le serveur · code <strong>{task.error_code}</strong>. Aucun résultat
                  n’est déclaré réussi.
                </span>
              </p>
            ) : null}

            {task.result_summary ? (
              <div style={{ marginTop: 16 }}>
                <h3 style={{ fontSize: '0.9375rem', marginBottom: 6 }}>Résultat</h3>
                <p style={{ color: 'var(--text-soft)', fontSize: '0.875rem', whiteSpace: 'pre-wrap' }}>
                  {task.result_summary}
                </p>
              </div>
            ) : null}
          </section>

          <section className="card card--pad" aria-labelledby="steps-title">
            <div className="panel-title">
              <h2 id="steps-title">Étapes</h2>
              <span className="meta">{steps.length} étape(s)</span>
            </div>
            {steps.length === 0 ? (
              <p className="muted" style={{ fontSize: '0.8125rem' }}>
                Aucune étape exposée par l’API pour cette mission.
              </p>
            ) : (
              <ol className="timeline">
                {steps.map((step, index) => {
                  const output = summarize(step.output_json);
                  return (
                    <li className="step" key={step.id} data-status={step.status}>
                      <span className="step__dot" aria-hidden="true">
                        {step.status === 'completed' ? '✓' : index + 1}
                      </span>
                      <div className="step__body">
                        <div className="step__title">
                          {step.title}
                          <StepPill status={step.status} />
                          {step.skill_id ? <span className="meta">skill {step.skill_id}</span> : null}
                        </div>
                        <p className="meta">
                          Clé {step.step_key}
                          {typeof step.attempt_count === 'number' ? ` · ${step.attempt_count} tentative(s)` : ''}
                          {' · '}
                          {formatDateTime(step.updated_at)}
                        </p>
                        {output ? <pre className="step__out">{output}</pre> : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>

        <aside className="stack">
          <section className="card card--pad" aria-labelledby="meta-title">
            <h2 id="meta-title" style={{ fontSize: '1rem', marginBottom: 10 }}>
              Détails
            </h2>
            <dl className="kv">
              <dt>Objectif</dt>
              <dd>{task.goal || '—'}</dd>
              <dt>Statut</dt>
              <dd>{task.status}</dd>
              <dt>Créée</dt>
              <dd>{formatDateTime(task.created_at)}</dd>
              <dt>Démarrée</dt>
              <dd>{formatDateTime(task.started_at)}</dd>
              <dt>Terminée</dt>
              <dd>{formatDateTime(task.completed_at)}</dd>
              <dt>ID</dt>
              <dd className="mono">{task.id}</dd>
            </dl>
          </section>

          <section className="card card--pad" aria-labelledby="events-title">
            <div className="panel-title">
              <h2 id="events-title">Événements</h2>
              <span className="badge">{events.length}</span>
            </div>
            <p className="meta" style={{ marginBottom: 8 }}>
              Reçus via WebSocket pendant cette session.
            </p>
            {events.length === 0 ? (
              <p className="muted" style={{ fontSize: '0.8125rem' }}>
                Aucun événement reçu. La progression affichée provient de la dernière lecture REST.
              </p>
            ) : (
              <ul className="event-log">
                {events.map((event) => (
                  <li key={event.event_id || `${event.event}-${event.timestamp}`}>
                    <time dateTime={event.timestamp}>{formatTime(event.timestamp)}</time>
                    <span>
                      {event.event}
                      {typeof (event.data as Record<string, unknown>).status === 'string'
                        ? ` · ${String((event.data as Record<string, unknown>).status)}`
                        : ''}
                      {typeof (event.data as Record<string, unknown>).progress === 'number'
                        ? ` · ${String((event.data as Record<string, unknown>).progress)} %`
                        : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>

      <ConfirmDialog
        open={confirmCancel}
        title="Annuler cette mission ?"
        description="L’annulation est demandée au serveur ; l’état final sera celui confirmé par l’API. Les étapes en cours seront interrompues."
        confirmLabel="Annuler la mission"
        cancelLabel="Conserver"
        tone="danger"
        busy={action === 'cancel'}
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => void runAction('cancel')}
      />
    </div>
  );
}
