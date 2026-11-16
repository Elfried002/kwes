import { useState } from 'react';
import {
  createConversation,
  deleteConversation,
  errorMessage,
  listConversations,
} from '../lib/api';
import { formatDateTime, formatRelative, truncate } from '../lib/format';
import { useApi } from '../lib/hooks';
import { usePreferences } from '../lib/prefs';
import { href, navigate } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';

/** Écran « Vos échanges » : l'historique des conversations, en langage courant. */
export function ConversationsScreen() {
  const { refreshKey, bumpRefresh } = useKwes();
  const prefs = usePreferences();
  const { data, error, loading, reload } = useApi(
    (signal) => listConversations(signal),
    [],
    { refreshKey },
  );
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const conversations = (data ?? []).slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  const create = async (): Promise<void> => {
    setCreating(true);
    setActionError(null);
    try {
      const conversation = await createConversation({ language: prefs.language });
      bumpRefresh();
      navigate({ name: 'chat', conversationId: conversation.id });
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCreating(false);
    }
  };

  const confirmDelete = async (): Promise<void> => {
    if (!pendingDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      await deleteConversation(pendingDelete);
      setPendingDelete(null);
      bumpRefresh();
      reload();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Retrouver</span>
          <h1>Vos échanges</h1>
          <p>Tout ce que vous avez dit à Kwes est gardé ici, sur votre compte.</p>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => void create()} disabled={creating}>
          <Icon name="plus" size={16} />
          {creating ? 'Ouverture…' : 'Commencer un échange'}
        </button>
      </div>

      {actionError ? (
        <p className="notice notice--danger" role="alert" style={{ marginBottom: 14 }}>
          {actionError}
        </p>
      ) : null}

      {loading && !data ? (
        <div className="stack" aria-hidden="true">
          <div className="skeleton skeleton--row" />
          <div className="skeleton skeleton--row" />
          <div className="skeleton skeleton--row" />
        </div>
      ) : error ? (
        <p className="notice notice--warning" role="alert">
          <Icon name="alert" size={16} />
          <span>
            Impossible de charger vos échanges : {errorMessage(error)}{' '}
            <button type="button" className="btn btn--ghost btn--sm" onClick={reload}>
              Réessayer
            </button>
          </span>
        </p>
      ) : conversations.length === 0 ? (
        <EmptyState
          title="Aucun échange pour l’instant"
          icon={<Icon name="history" size={26} />}
          action={
            <a className="btn btn--soft" href={href({ name: 'chat' })}>
              Parler à Kwes
            </a>
          }
        >
          Votre première conversation apparaîtra ici dès que vous aurez écrit à Kwes.
        </EmptyState>
      ) : (
        <div className="list" role="list">
          {conversations.map((conversation) => (
            <div className="list__row card--hover" role="listitem" key={conversation.id}>
              <div className="list__main">
                <a className="list__title" href={href({ name: 'chat', conversationId: conversation.id })}>
                  {truncate(conversation.title?.trim() || 'Sans titre', 90)}
                </a>
                <div className="list__meta">
                  <span>{formatRelative(conversation.updated_at)}</span>
                  <span title={formatDateTime(conversation.created_at)}>
                    commencé le {formatDateTime(conversation.created_at)}
                  </span>
                </div>
              </div>
              <div className="list__side">
                <a className="btn btn--sm" href={href({ name: 'chat', conversationId: conversation.id })}>
                  Reprendre
                </a>
                <button
                  type="button"
                  className="btn btn--danger btn--sm"
                  onClick={() => setPendingDelete(conversation.id)}
                  aria-label={`Supprimer l’échange ${conversation.title ?? 'sans titre'}`}
                >
                  <Icon name="trash" size={13} />
                  Supprimer
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Supprimer cet échange ?"
        description="La conversation et ses messages seront supprimés définitivement."
        confirmLabel="Supprimer"
        tone="danger"
        busy={deleting}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
