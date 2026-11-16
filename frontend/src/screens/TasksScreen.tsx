import { useState } from 'react';
import { errorMessage, listTasks } from '../lib/api';
import { clampProgress, formatRelative } from '../lib/format';
import { useApi } from '../lib/hooks';
import { href } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import { StatusPill } from '../components/StatusPill';
import type { Task, TaskStatus } from '../lib/types';

type FilterKey = 'all' | 'active' | 'awaiting' | 'completed' | 'failed';

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: 'Tout' },
  { key: 'active', label: 'En cours' },
  { key: 'awaiting', label: 'Votre accord attendu' },
  { key: 'completed', label: 'Terminé' },
  { key: 'failed', label: 'N’a pas abouti' },
];

function matches(task: Task, filter: FilterKey): boolean {
  const status: TaskStatus = task.status;
  switch (filter) {
    case 'all':
      return true;
    case 'active':
      return status === 'running' || status === 'planning' || status === 'queued' || status === 'paused';
    case 'awaiting':
      return status === 'awaiting_approval';
    case 'completed':
      return status === 'completed' || status === 'cancelled';
    case 'failed':
      return status === 'failed';
  }
}

export function TasksScreen() {
  const { refreshKey } = useKwes();
  const { data, error, loading, reload } = useApi(
    (signal) => listTasks(signal),
    [],
    { refreshKey },
  );
  const [filter, setFilter] = useState<FilterKey>('all');

  const tasks = (data ?? []).slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const visible = tasks.filter((task) => matches(task, filter));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Son travail</span>
          <h1>Ce que Kwes fait</h1>
          <p>
            Voici ce sur quoi il travaille, ce qu’il a terminé et ce qui attend votre accord. Chaque
            ligne s’ouvre sur le détail de son avancement.
          </p>
        </div>
        <button type="button" className="btn" onClick={reload} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? 'Actualisation…' : 'Actualiser'}
        </button>
      </div>

      <div className="filters" role="group" aria-label="Filtrer son travail">
        {FILTERS.map((entry) => {
          const count = tasks.filter((task) => matches(task, entry.key)).length;
          return (
            <button
              key={entry.key}
              type="button"
              className="filter"
              aria-pressed={filter === entry.key}
              onClick={() => setFilter(entry.key)}
            >
              {entry.label} <span className="meta">({count})</span>
            </button>
          );
        })}
      </div>

      {error ? (
        <p className="notice notice--warning" role="alert">
          <Icon name="alert" size={16} />
          <span>
            Impossible de charger son travail : {errorMessage(error)}{' '}
            <button type="button" className="btn btn--ghost btn--sm" onClick={reload}>
              Réessayer
            </button>
          </span>
        </p>
      ) : loading && !data ? (
        <div className="stack" aria-hidden="true">
          <div className="skeleton skeleton--row" />
          <div className="skeleton skeleton--row" />
          <div className="skeleton skeleton--row" />
        </div>
      ) : visible.length === 0 ? (
        <EmptyState title="Rien dans cette vue" icon={<Icon name="activity" size={26} />}>
          {tasks.length === 0
            ? 'Dès que vous confiez quelque chose à Kwes, son travail apparaît ici.'
            : 'Changez de filtre pour voir le reste de son travail.'}
        </EmptyState>
      ) : (
        <div className="list" role="list">
          {visible.map((task) => {
            const progress = clampProgress(task.progress);
            const barClass =
              task.status === 'completed'
                ? 'progress__bar progress__bar--success'
                : task.status === 'failed'
                  ? 'progress__bar progress__bar--danger'
                  : task.status === 'awaiting_approval'
                    ? 'progress__bar progress__bar--warning'
                    : 'progress__bar';
            return (
              <div className="list__row card--hover" role="listitem" key={task.id}>
                <div className="list__main">
                  <a className="list__title" href={href({ name: 'task', id: task.id })}>
                    {task.title}
                  </a>
                  <div className="list__meta">
                    <StatusPill status={task.status} />
                    <span>Mis à jour {formatRelative(task.updated_at)}</span>
                  </div>
                  <div className="progress-row" style={{ marginTop: 4, maxWidth: 520 }}>
                    <div
                      className="progress"
                      role="progressbar"
                      aria-valuenow={progress}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Avancement de ${task.title}`}
                    >
                      <div className={barClass} style={{ width: `${progress}%` }} />
                    </div>
                    <span className="progress-row__value">{progress} %</span>
                  </div>
                </div>
                <div className="list__side">
                  <a className="btn btn--sm" href={href({ name: 'task', id: task.id })}>
                    Voir
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
