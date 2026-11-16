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
  { key: 'all', label: 'Toutes' },
  { key: 'active', label: 'En cours' },
  { key: 'awaiting', label: 'En attente' },
  { key: 'completed', label: 'Terminées' },
  { key: 'failed', label: 'Échouées' },
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
          <span className="page-head__eyebrow">Activités</span>
          <h1>Missions</h1>
          <p>
            Progression, statut et résultat proviennent du serveur. L’Orb suit les événements
            <code className="mono"> task.*</code> en temps réel.
          </p>
        </div>
        <button type="button" className="btn" onClick={reload} disabled={loading}>
          <Icon name="refresh" size={16} />
          {loading ? 'Actualisation…' : 'Actualiser'}
        </button>
      </div>

      <div className="filters" role="group" aria-label="Filtrer les missions">
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
            Impossible de charger les missions : {errorMessage(error)}{' '}
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
        <EmptyState title="Aucune mission dans ce filtre" icon={<Icon name="activity" size={26} />}>
          {tasks.length === 0
            ? 'Les missions apparaîtront ici dès qu’une demande en créera une côté serveur.'
            : 'Changez de filtre pour consulter les autres missions.'}
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
              <div className="list__row" role="listitem" key={task.id}>
                <div className="list__main">
                  <a className="list__title" href={href({ name: 'task', id: task.id })}>
                    {task.title}
                  </a>
                  <div className="list__meta">
                    <StatusPill status={task.status} />
                    {task.priority ? <span>Priorité {task.priority}</span> : null}
                    <span>MAJ {formatRelative(task.updated_at)}</span>
                    {task.error_code ? <span className="badge badge--danger">{task.error_code}</span> : null}
                    {task.is_demo ? <span className="badge badge--demo">[DEMO]</span> : null}
                  </div>
                  <div className="progress-row" style={{ marginTop: 4, maxWidth: 520 }}>
                    <div
                      className="progress"
                      role="progressbar"
                      aria-valuenow={progress}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-label={`Progression de ${task.title}`}
                    >
                      <div className={barClass} style={{ width: `${progress}%` }} />
                    </div>
                    <span className="progress-row__value">{progress} %</span>
                  </div>
                </div>
                <div className="list__side">
                  <a className="btn btn--sm" href={href({ name: 'task', id: task.id })}>
                    Détail
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
