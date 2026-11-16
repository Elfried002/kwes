import { useState } from 'react';
import {
  createConversation,
  deleteConversation,
  errorMessage,
  listConversations,
} from '../lib/api';
import { formatRelative, truncate } from '../lib/format';
import { useApi } from '../lib/hooks';
import { usePreferences } from '../lib/prefs';
import { href, navigate } from '../lib/router';
import { useKwes } from '../state/KwesProvider';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Icon } from '../components/Icon';

/**
 * Historique des conversations : une liste, rien de plus.
 * Titre tronqué, date relative discrète, suppression au survol.
 */
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
    <div className="hist">
      <header className="hist__head">
        <h1>Récentes</h1>
        <button type="button" className="hist__new" onClick={() => void create()} disabled={creating}>
          <Icon name="plus" size={16} />
          {creating ? 'Ouverture…' : 'Nouvelle conversation'}
        </button>
      </header>

      {actionError ? (
        <p className="hist__error" role="alert">
          {actionError}
        </p>
      ) : null}

      {loading && !data ? (
        <p className="hist__hint">Chargement…</p>
      ) : error ? (
        <p className="hist__hint hist__hint--error" role="alert">
          {errorMessage(error)}{' '}
          <button type="button" className="hist__link" onClick={reload}>
            Réessayer
          </button>
        </p>
      ) : conversations.length === 0 ? (
        <div className="hist__hint">
          <p>Aucune conversation pour l’instant.</p>
          <p>
            <a className="hist__link" href={href({ name: 'chat' })}>
              Écrire à Kwes
            </a>
          </p>
        </div>
      ) : (
        <ul className="hist__list">
          {conversations.map((conversation) => {
            const label = truncate(conversation.title?.trim() || 'Sans titre', 40);
            return (
              <li className="hist__row" key={conversation.id}>
                <a
                  className="hist__link-main"
                  href={href({ name: 'chat', conversationId: conversation.id })}
                  title={conversation.title?.trim() || 'Sans titre'}
                >
                  <span className="hist__convo">{label}</span>
                  <time className="hist__date" dateTime={conversation.updated_at}>
                    {formatRelative(conversation.updated_at)}
                  </time>
                </a>
                <button
                  type="button"
                  className="hist__remove"
                  onClick={() => setPendingDelete(conversation.id)}
                  aria-label={`Supprimer ${label}`}
                  title="Supprimer"
                >
                  <Icon name="trash" size={15} />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Supprimer cette conversation ?"
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
