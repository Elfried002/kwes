import { useState } from 'react';
import {
  approveRequest,
  errorMessage,
  listApprovals,
  rejectRequest,
} from '../lib/api';
import { formatCountdown, formatDateTime, formatRelative } from '../lib/format';
import { useApi, useNow } from '../lib/hooks';
import { href } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import type { Approval } from '../lib/types';

const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: 'En attente',
  approved: 'Approuvée',
  rejected: 'Refusée',
  expired: 'Expirée',
};

interface PendingDecision {
  approval: Approval;
  decision: 'approve' | 'reject';
}

export function ApprovalsScreen() {
  const { refreshKey, bumpRefresh, notifyApprovalDecided } = useKwes();
  const { data, error, loading, reload } = useApi(
    (signal) => listApprovals(signal),
    [],
    { refreshKey },
  );
  const [pendingDecision, setPendingDecision] = useState<PendingDecision | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  useNow(30_000);

  const approvals = data ?? [];
  const pending = approvals.filter((approval) => approval.status === 'pending');
  const history = approvals.filter((approval) => approval.status !== 'pending');

  const decide = async (): Promise<void> => {
    if (!pendingDecision) return;
    const { approval, decision } = pendingDecision;
    setBusyId(approval.id);
    setActionError(null);
    setActionNotice(null);
    try {
      if (decision === 'approve') await approveRequest(approval.id);
      else await rejectRequest(approval.id);
      setPendingDecision(null);
      notifyApprovalDecided(
        approval.task_id,
        decision === 'approve' ? 'approved' : 'rejected',
      );
      setActionNotice(
        decision === 'approve'
          ? `Validation envoyée pour « ${approval.summary} ». La mission reprendra selon le serveur.`
          : `Refus envoyé pour « ${approval.summary} ».`,
      );
      bumpRefresh();
      reload();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  };

  const isExpired = (approval: Approval): boolean => {
    if (!approval.expires_at) return false;
    const time = new Date(approval.expires_at).getTime();
    return Number.isFinite(time) && time <= Date.now();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Contrôle</span>
          <h1>Validations</h1>
          <p>
            Toute action sensible attend votre décision. Le policy engine reste côté serveur ;
            l’approbation est liée à un hash de charge utile et expire.
          </p>
        </div>
        <div className="row">
          <span className={`badge ${pending.length > 0 ? 'badge--warning' : 'badge--success'}`}>
            {pending.length} en attente
          </span>
          <button type="button" className="btn" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={16} />
            Actualiser
          </button>
        </div>
      </div>

      {actionError ? (
        <p className="notice notice--danger" role="alert" style={{ marginBottom: 14 }}>
          {actionError}
        </p>
      ) : null}
      {actionNotice ? (
        <p className="notice notice--success" role="status" style={{ marginBottom: 14 }}>
          {actionNotice}
        </p>
      ) : null}

      {error ? (
        <p className="notice notice--warning" role="alert">
          <Icon name="alert" size={16} />
          <span>
            Impossible de charger les validations : {errorMessage(error)}{' '}
            <button type="button" className="btn btn--ghost btn--sm" onClick={reload}>
              Réessayer
            </button>
          </span>
        </p>
      ) : loading && !data ? (
        <div className="stack" aria-hidden="true">
          <div className="skeleton skeleton--block" />
          <div className="skeleton skeleton--block" />
        </div>
      ) : (
        <>
          <section aria-labelledby="pending-title" className="stack" style={{ marginBottom: 'var(--sp-6)' }}>
            <div className="panel-title">
              <h2 id="pending-title">En attente de votre décision</h2>
            </div>

            {pending.length === 0 ? (
              <EmptyState title="Aucune validation en attente" icon={<Icon name="shield" size={26} />}>
                Kwes vous sollicitera ici avant toute action sensible.
              </EmptyState>
            ) : (
              pending.map((approval) => {
                const expired = isExpired(approval);
                return (
                  <article className="approval" key={approval.id} aria-labelledby={`approval-${approval.id}`}>
                    <div className="approval__head">
                      <span className={`badge ${expired ? 'badge--danger' : 'badge--warning'}`}>
                        {expired ? 'Expirée' : formatCountdown(approval.expires_at)}
                      </span>
                      <span className="badge">{approval.action_type}</span>
                      {approval.is_demo ? <span className="badge badge--demo">[DEMO]</span> : null}
                    </div>
                    <h3 id={`approval-${approval.id}`} className="approval__summary">
                      {approval.summary}
                    </h3>
                    <div className="row row--between">
                      <span className="meta">
                        Mission{' '}
                        <a href={href({ name: 'task', id: approval.task_id })} className="mono">
                          {approval.task_id.slice(0, 8)}…
                        </a>
                        {approval.expires_at ? ` · échéance ${formatDateTime(approval.expires_at)}` : ''}
                      </span>
                      {approval.payload_hash ? (
                        <span className="approval__hash" title={approval.payload_hash}>
                          hash {approval.payload_hash.slice(0, 16)}…
                        </span>
                      ) : null}
                    </div>
                    <div className="row" style={{ justifyContent: 'flex-end' }}>
                      <button
                        type="button"
                        className="btn btn--danger"
                        onClick={() => setPendingDecision({ approval, decision: 'reject' })}
                        disabled={busyId !== null || expired}
                      >
                        Refuser
                      </button>
                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => setPendingDecision({ approval, decision: 'approve' })}
                        disabled={busyId !== null || expired}
                      >
                        <Icon name="check" size={15} />
                        Approuver
                      </button>
                    </div>
                    {expired ? (
                      <p className="meta">Cette demande a expiré ; une nouvelle validation sera nécessaire.</p>
                    ) : null}
                  </article>
                );
              })
            )}
          </section>

          <section aria-labelledby="history-title">
            <div className="panel-title">
              <h2 id="history-title">Historique des décisions</h2>
              <span className="meta">{history.length}</span>
            </div>
            {history.length === 0 ? (
              <p className="muted" style={{ fontSize: '0.8125rem' }}>
                Aucune décision enregistrée pour le moment.
              </p>
            ) : (
              <div className="list">
                {history.map((approval) => (
                  <div className="list__row" key={approval.id}>
                    <div className="list__main">
                      <span className="list__title">{approval.summary}</span>
                      <div className="list__meta">
                        <span className={`badge ${approval.status === 'approved' ? 'badge--success' : approval.status === 'rejected' ? 'badge--danger' : ''}`}>
                          {APPROVAL_STATUS_LABELS[approval.status] ?? approval.status}
                        </span>
                        <span>{approval.action_type}</span>
                        <span>décidé {formatRelative(approval.decided_at)}</span>
                      </div>
                    </div>
                    <div className="list__side">
                      <a className="btn btn--ghost btn--sm" href={href({ name: 'task', id: approval.task_id })}>
                        Mission
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <ConfirmDialog
        open={pendingDecision !== null}
        title={pendingDecision?.decision === 'approve' ? 'Approuver cette action ?' : 'Refuser cette action ?'}
        description={
          pendingDecision?.decision === 'approve'
            ? `« ${pendingDecision?.approval.summary ?? ''} » — l’approbation autorise le serveur à exécuter cette action liée au hash de charge utile.`
            : `« ${pendingDecision?.approval.summary ?? ''} » — le refus empêche l’exécution de cette action.`
        }
        confirmLabel={pendingDecision?.decision === 'approve' ? 'Approuver' : 'Refuser'}
        tone={pendingDecision?.decision === 'approve' ? 'primary' : 'danger'}
        busy={busyId !== null}
        onCancel={() => setPendingDecision(null)}
        onConfirm={() => void decide()}
      />
    </div>
  );
}
