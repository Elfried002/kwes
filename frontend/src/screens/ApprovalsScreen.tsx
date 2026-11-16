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
  approved: 'Acceptée',
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
          ? `C’est noté : Kwes peut faire « ${approval.summary} ».`
          : `C’est noté : Kwes ne fera pas « ${approval.summary} ».`,
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
          <span className="page-head__eyebrow">À vous de décider</span>
          <h1>Il attend votre accord</h1>
          <p>
            Kwes s’arrête dès qu’une action peut avoir des conséquences. Lisez ce qu’il veut faire,
            puis acceptez ou refusez. Chaque demande expire si vous ne répondez pas.
          </p>
        </div>
        <div className="row">
          <span className={`badge ${pending.length > 0 ? 'badge--warning' : 'badge--success'}`}>
            {pending.length === 0
              ? 'Rien en attente'
              : `${pending.length} demande${pending.length > 1 ? 's' : ''}`}
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
            Impossible de charger les demandes : {errorMessage(error)}{' '}
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
              <h2 id="pending-title">Ce qu’il veut faire</h2>
            </div>

            {pending.length === 0 ? (
              <EmptyState title="Rien à décider pour le moment" icon={<Icon name="shield" size={26} />}>
                Kwes vous préviendra ici avant toute action délicate.
              </EmptyState>
            ) : (
              pending.map((approval) => {
                const expired = isExpired(approval);
                return (
                  <article
                    className="approval"
                    key={approval.id}
                    aria-labelledby={`approval-${approval.id}`}
                  >
                    <div className="approval__head">
                      <span className={`badge ${expired ? 'badge--danger' : 'badge--warning'}`}>
                        {expired ? 'Expirée' : formatCountdown(approval.expires_at)}
                      </span>
                    </div>
                    <h3 id={`approval-${approval.id}`} className="approval__summary">
                      {approval.summary}
                    </h3>
                    <div className="approval__meta">
                      <a className="meta" href={href({ name: 'task', id: approval.task_id })}>
                        Voir le travail en cours
                      </a>
                      {approval.expires_at ? (
                        <span className="meta">
                          Valable jusqu’au {formatDateTime(approval.expires_at)}
                        </span>
                      ) : null}
                    </div>
                    <div className="approval__foot">
                      {approval.action_type || approval.payload_hash ? (
                        <details className="disclosure">
                          <summary>Détails</summary>
                          <p className="meta">
                            {approval.action_type ? `Type d’action : ${approval.action_type}` : ''}
                            {approval.payload_hash
                              ? ` · Empreinte de la demande : ${approval.payload_hash.slice(0, 16)}…`
                              : ''}
                          </p>
                        </details>
                      ) : (
                        <span />
                      )}
                      <div className="row">
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
                          Accepter
                        </button>
                      </div>
                    </div>
                    {expired ? (
                      <p className="meta">
                        Cette demande a expiré. Kwes vous en préparera une nouvelle s’il en a besoin.
                      </p>
                    ) : null}
                  </article>
                );
              })
            )}
          </section>

          <section aria-labelledby="history-title">
            <div className="panel-title">
              <h2 id="history-title">Décisions passées</h2>
              <span className="meta">{history.length}</span>
            </div>
            {history.length === 0 ? (
              <p className="muted" style={{ fontSize: '0.8125rem' }}>
                Vous n’avez encore rien eu à décider.
              </p>
            ) : (
              <div className="list">
                {history.map((approval) => (
                  <div className="list__row" key={approval.id}>
                    <div className="list__main">
                      <span className="list__title">{approval.summary}</span>
                      <div className="list__meta">
                        <span
                          className={`badge ${approval.status === 'approved' ? 'badge--success' : approval.status === 'rejected' ? 'badge--danger' : ''}`}
                        >
                          {APPROVAL_STATUS_LABELS[approval.status] ?? approval.status}
                        </span>
                        <span>{formatRelative(approval.decided_at)}</span>
                      </div>
                    </div>
                    <div className="list__side">
                      <a className="btn btn--ghost btn--sm" href={href({ name: 'task', id: approval.task_id })}>
                        Voir
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
        title={pendingDecision?.decision === 'approve' ? 'Accepter cette action ?' : 'Refuser cette action ?'}
        description={
          pendingDecision?.decision === 'approve'
            ? `Kwes pourra faire « ${pendingDecision?.approval.summary ?? ''} ». Votre accord part tout de suite et ne peut plus être retiré.`
            : `Kwes ne fera pas « ${pendingDecision?.approval.summary ?? ''} ». Vous pourrez le lui redemander plus tard.`
        }
        confirmLabel={pendingDecision?.decision === 'approve' ? 'Accepter' : 'Refuser'}
        tone={pendingDecision?.decision === 'approve' ? 'primary' : 'danger'}
        busy={busyId !== null}
        onCancel={() => setPendingDecision(null)}
        onConfirm={() => void decide()}
      />
    </div>
  );
}
