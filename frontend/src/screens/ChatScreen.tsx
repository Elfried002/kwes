import { useEffect, useRef, useState } from 'react';
import {
  deleteConversation,
  errorMessage,
  listConversations,
  listMessages,
  sendChat,
} from '../lib/api';
import { formatRelative, truncate } from '../lib/format';
import { usePrefersReducedMotion } from '../lib/hooks';
import { readDraft, usePreferences, writeDraft } from '../lib/prefs';
import { href, navigate } from '../lib/router';
import { type Conversation, type ConversationDeltaData, type Message } from '../lib/types';
import { useKwes } from '../state/KwesProvider';
import { Composer } from '../components/Composer';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Icon } from '../components/Icon';
import { MessageBubble } from '../components/MessageBubble';

interface TypingState {
  message: Message;
  shown: number;
}

function mergeMessages(server: Message[], local: Message[]): Message[] {
  const serverIds = new Set(server.map((message) => message.id));
  const extras = local.filter((message) => {
    if (serverIds.has(message.id)) return false;
    const duplicate = server.some(
      (candidate) =>
        candidate.role === message.role && candidate.content.trim() === message.content.trim(),
    );
    return !duplicate;
  });
  return [...server, ...extras];
}

/**
 * Fil de conversation : un titre, les messages, une barre de saisie.
 * La liste des conversations sert de repère latéral et passe sous un bouton
 * d'en-tête sur mobile ; la voix vit sur son propre écran.
 */
export function ChatScreen({ conversationId }: { conversationId?: string }) {
  const { refreshKey, bumpRefresh, notifyChatStarted, notifyChatAnswered, notifyApiError, resetOrb, subscribe } =
    useKwes();
  const prefs = usePreferences();
  const reducedMotion = usePrefersReducedMotion();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [loadingMessages, setLoadingMessages] = useState(Boolean(conversationId));
  const [messagesNonce, setMessagesNonce] = useState(0);
  const [draft, setDraft] = useState(() => readDraft(conversationId ?? 'new'));
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [streaming, setStreaming] = useState('');
  const [typing, setTyping] = useState<TypingState | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const conversationRef = useRef<string | undefined>(conversationId);
  conversationRef.current = conversationId;

  const conversation = conversations.find((item) => item.id === conversationId) ?? null;
  const title = conversation?.title?.trim() || (conversationId ? 'Conversation' : 'Nouvelle conversation');

  useEffect(() => {
    const controller = new AbortController();
    listConversations(controller.signal)
      .then((result) => {
        setConversations(result);
        setConversationsError(null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setConversationsError(errorMessage(cause));
      });
    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      setLoadingMessages(false);
      setMessagesError(null);
      return;
    }
    const controller = new AbortController();
    setLoadingMessages((previous) => previous || messages.length === 0);
    listMessages(conversationId, controller.signal)
      .then((result) => {
        setMessages((previous) =>
          mergeMessages(
            result,
            previous.filter(
              (message) => message.conversation_id === conversationId || message.conversation_id === 'pending',
            ),
          ),
        );
        setMessagesError(null);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setMessagesError(errorMessage(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingMessages(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, refreshKey, messagesNonce]);

  useEffect(() => {
    setDraft(readDraft(conversationId ?? 'new'));
    setStreaming('');
    // Ne pas interrompre un affichage progressif qui appartient déjà à cette conversation
    // (cas d'un premier envoi : l'ID est obtenu après le POST puis reflété dans l'URL).
    setTyping((current) =>
      current && current.message.conversation_id === conversationId ? current : null,
    );
    setMessages((previous) =>
      conversationId
        ? previous.filter(
            (message) =>
              message.conversation_id === conversationId || message.conversation_id === 'pending',
          )
        : [],
    );
    setListOpen(false);
    setMenuOpen(false);
  }, [conversationId]);

  useEffect(() => {
    writeDraft(conversationId ?? 'new', draft);
  }, [draft, conversationId]);

  // Deltas temps réel : affichés comme brouillon, remplacés par la réponse REST finale.
  useEffect(() => {
    return subscribe((envelope) => {
      if (envelope.event !== 'conversation.delta') return;
      const data = (envelope.data ?? {}) as ConversationDeltaData;
      const target = conversationRef.current;
      if (target && data.conversation_id && data.conversation_id !== target) return;
      if (!target) return;
      const chunk = typeof data.delta === 'string' ? data.delta : typeof data.content === 'string' ? data.content : '';
      if (chunk) setStreaming((previous) => previous + chunk);
    });
  }, [subscribe]);

  // Streaming simulé uniquement hors WebSocket, à partir de la réponse REST réelle.
  useEffect(() => {
    if (!typing) return;
    if (typing.shown >= typing.message.content.length) {
      const finished = typing.message;
      setMessages((previous) => {
        const duplicate = previous.some(
          (message) =>
            message.role === 'assistant' && message.content.trim() === finished.content.trim(),
        );
        return duplicate ? previous : [...previous, finished];
      });
      setTyping(null);
      return;
    }
    const step = Math.max(3, Math.ceil(typing.message.content.length / 90));
    const timer = window.setTimeout(() => {
      setTyping((current) =>
        current
          ? {
              message: current.message,
              shown: Math.min(current.message.content.length, current.shown + step),
            }
          : null,
      );
    }, 24);
    return () => window.clearTimeout(timer);
  }, [typing]);

  useEffect(() => {
    if (messages.length === 0 && !typing && !streaming) return;
    bottomRef.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'end' });
  }, [messages, typing, streaming, reducedMotion]);

  // Tiroir mobile : Échap le referme.
  useEffect(() => {
    if (!listOpen) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setListOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [listOpen]);

  // Menus : fermeture au clic extérieur et à Échap.
  useEffect(() => {
    if (!menuOpen) return;
    const onPointer = (event: MouseEvent): void => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const sendMessage = async (raw: string): Promise<void> => {
    const text = raw.trim();
    if (!text || sending) return;
    const currentConversation = conversationRef.current ?? null;
    const key = currentConversation ?? 'new';
    const optimisticId = `local-user-${Date.now()}`;
    const optimistic: Message = {
      id: optimisticId,
      conversation_id: currentConversation ?? 'pending',
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      metadata: { optimistic: true },
    };

    setMessages((previous) => [...previous, optimistic]);
    setDraft('');
    writeDraft(key, '');
    setSendError(null);
    setNotice(null);
    setStreaming('');
    setSending(true);
    notifyChatStarted();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await sendChat(
        { conversation_id: currentConversation, message: text, language: prefs.language, mode: 'auto' },
        controller.signal,
      );

      setMessages((previous) =>
        previous.map((message) =>
          message.id === optimisticId ? { ...message, conversation_id: result.conversation_id } : message,
        ),
      );
      setStreaming('');
      notifyChatAnswered();
      bumpRefresh();

      const assistant: Message = {
        id: result.message_id || `local-assistant-${Date.now()}`,
        conversation_id: result.conversation_id,
        role: 'assistant',
        content: result.response,
        created_at: new Date().toISOString(),
        metadata: {},
      };

      setMessages((previous) => [...previous, assistant]);

      if (!currentConversation) {
        navigate({ name: 'chat', conversationId: result.conversation_id }, { replace: true });
      }
    } catch (cause) {
      setMessages((previous) => previous.filter((message) => message.id !== optimisticId));
      writeDraft(key, text);
      setDraft(text);
      if (controller.signal.aborted) {
        setNotice('Envoi interrompu avant la réponse.');
        resetOrb();
      } else {
        setSendError(errorMessage(cause));
        notifyApiError(cause);
      }
    } finally {
      setSending(false);
      abortRef.current = null;
    }
  };

  const handleCopy = async (message: Message): Promise<void> => {
    try {
      await navigator.clipboard.writeText(message.content);
      setNotice('Message copié.');
    } catch {
      setNotice('Copie impossible depuis ce navigateur.');
    }
  };

  const retry = (assistantMessage: Message): void => {
    const index = messages.findIndex((message) => message.id === assistantMessage.id);
    const previousUser = messages
      .slice(0, index < 0 ? messages.length : index)
      .reverse()
      .find((message) => message.role === 'user');
    if (!previousUser) {
      setNotice('Aucun message à relancer.');
      return;
    }
    void sendMessage(previousUser.content);
  };

  const removeConversation = async (): Promise<void> => {
    if (!conversationId) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteConversation(conversationId);
      setPendingDelete(false);
      bumpRefresh();
      navigate({ name: 'chat' });
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleting(false);
    }
  };

  const busy = sending && !streaming;

  return (
    <div className="convo">
      <aside className={`convo__list${listOpen ? ' is-open' : ''}`} aria-label="Vos conversations">
        <div className="convo__list-head">
          <span>Récentes</span>
          <button
            type="button"
            className="convo__icon"
            aria-label="Nouvelle conversation"
            title="Nouvelle conversation"
            onClick={() => navigate({ name: 'chat' })}
          >
            <Icon name="plus" size={17} />
          </button>
        </div>
        <nav className="convo__items">
          {conversationsError ? <p className="convo__list-empty">{conversationsError}</p> : null}
          {conversations.length === 0 && !conversationsError ? (
            <p className="convo__list-empty">Aucune conversation pour l’instant.</p>
          ) : null}
          {conversations.slice(0, 40).map((item) => (
            <a
              key={item.id}
              className="convo__item"
              href={href({ name: 'chat', conversationId: item.id })}
              aria-current={item.id === conversationId ? 'page' : undefined}
              title={item.title?.trim() || 'Sans titre'}
            >
              <span className="convo__item-title">{truncate(item.title?.trim() || 'Sans titre', 40)}</span>
              <span className="convo__item-date">{formatRelative(item.updated_at)}</span>
            </a>
          ))}
        </nav>
        <a className="convo__list-all" href={href({ name: 'conversations' })}>
          Tout voir
        </a>
      </aside>

      {listOpen ? (
        <button
          type="button"
          className="convo__scrim"
          aria-label="Fermer la liste des conversations"
          onClick={() => setListOpen(false)}
        />
      ) : null}

      <section className="convo__main" aria-label="Conversation">
        <header className="convo__head">
          <button
            type="button"
            className="convo__icon convo__icon--menu"
            aria-label="Vos conversations"
            aria-expanded={listOpen}
            onClick={() => setListOpen((value) => !value)}
          >
            <Icon name="menu" size={19} />
          </button>
          <h1 className="convo__title" title={title}>
            {title}
          </h1>
          <div className="convo__menu" ref={menuRef}>
            <button
              type="button"
              className="convo__icon"
              aria-label="Options de la conversation"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((value) => !value)}
            >
              <Icon name="more" size={18} />
            </button>
            {menuOpen ? (
              <div className="convo__pop" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  className="convo__pop-item convo__pop-item--danger"
                  onClick={() => {
                    setMenuOpen(false);
                    setPendingDelete(true);
                  }}
                  disabled={!conversationId}
                >
                  <Icon name="trash" size={15} />
                  Supprimer
                </button>
              </div>
            ) : null}
          </div>
        </header>

        <div className="convo__thread" aria-live="polite" aria-busy={sending}>
          {loadingMessages && messages.length === 0 ? (
            <p className="convo__hint">Chargement de la conversation…</p>
          ) : null}

          {messagesError ? (
            <p className="convo__hint convo__hint--error" role="alert">
              {messagesError}{' '}
              <button
                type="button"
                className="convo__link"
                onClick={() => setMessagesNonce((value) => value + 1)}
              >
                Réessayer
              </button>
            </p>
          ) : null}

          {!loadingMessages && messages.length === 0 && !messagesError && !typing && !streaming ? (
            <div className="convo__empty">
              <p>{conversationId ? 'Cette conversation est vide.' : 'Que souhaitez-vous faire ?'}</p>
            </div>
          ) : null}

          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onCopy={(item) => {
                void handleCopy(item);
              }}
              onRetry={retry}
            />
          ))}

          {typing ? (
            <MessageBubble
              message={{ ...typing.message, content: typing.message.content.slice(0, typing.shown) }}
              onCopy={() => undefined}
              streaming
            />
          ) : null}

          {streaming ? (
            <MessageBubble
              message={{
                id: 'streaming',
                conversation_id: conversationId ?? 'pending',
                role: 'assistant',
                content: streaming,
                created_at: new Date().toISOString(),
              }}
              onCopy={() => undefined}
              streaming
            />
          ) : null}

          {busy && !typing ? <p className="convo__status">Kwes écrit…</p> : null}

          <div ref={bottomRef} />
        </div>

        <div className="convo__compose">
          {sendError ? (
            <p className="convo__hint convo__hint--error" role="alert">
              {sendError} Votre message est resté dans le champ.
            </p>
          ) : null}
          {deleteError ? (
            <p className="convo__hint convo__hint--error" role="alert">
              {deleteError}
            </p>
          ) : null}
          {notice ? (
            <p className="convo__hint" role="status">
              {notice}
            </p>
          ) : null}

          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => {
              void sendMessage(draft);
            }}
            busy={sending}
            onVoice={() => {
              window.location.hash = href({ name: 'voice' });
            }}
            onStop={() => abortRef.current?.abort()}
            micAllowed={false}
            autoFocus
            placeholder={conversationId ? 'Poursuivre la conversation…' : 'Écrivez à Kwes…'}
            hint="Entrée pour envoyer, Maj+Entrée pour revenir à la ligne."
          />
        </div>
      </section>

      <ConfirmDialog
        open={pendingDelete}
        title="Supprimer cette conversation ?"
        description="La conversation et ses messages seront supprimés définitivement."
        confirmLabel="Supprimer"
        tone="danger"
        busy={deleting}
        onCancel={() => setPendingDelete(false)}
        onConfirm={() => void removeConversation()}
      />
    </div>
  );
}
