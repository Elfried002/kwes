import { useEffect, useRef, useState } from 'react';
import { errorMessage, listConversations, listMessages, sendChat } from '../lib/api';
import { formatRelative, truncate } from '../lib/format';
import { usePrefersReducedMotion } from '../lib/hooks';
import { readDraft, usePreferences, writeDraft } from '../lib/prefs';
import { href, navigate } from '../lib/router';
import { isRecord, type Conversation, type ConversationDeltaData, type Message } from '../lib/types';
import { useKwes } from '../state/KwesProvider';
import { Composer } from '../components/Composer';
import { EmptyState } from '../components/EmptyState';
import { Icon } from '../components/Icon';
import { MessageBubble } from '../components/MessageBubble';
import { HybridOrb } from '../components/orb/HybridOrb';

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

function sourcesLabel(metadata: Record<string, unknown> | null | undefined): string | null {
  if (!metadata) return null;
  if (isRecord(metadata.task) && typeof metadata.task.id === 'string') return metadata.task.id;
  return null;
}

export function ChatScreen({ conversationId }: { conversationId?: string }) {
  const {
    connection,
    refreshKey,
    bumpRefresh,
    notifyChatStarted,
    notifyChatAnswered,
    notifyApiError,
    resetOrb,
    subscribe,
    setMicActive,
    orbState,
  } = useKwes();
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

  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
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
    const wasOnline = connection === 'online';

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
        metadata: wasOnline ? {} : { simulated: true },
      };

      if (wasOnline) {
        setMessages((previous) => [...previous, assistant]);
      } else {
        setTyping({ message: assistant, shown: 0 });
      }

      if (!currentConversation) {
        navigate({ name: 'chat', conversationId: result.conversation_id }, { replace: true });
      }
    } catch (cause) {
      setMessages((previous) => previous.filter((message) => message.id !== optimisticId));
      writeDraft(key, text);
      setDraft(text);
      if (controller.signal.aborted) {
        setNotice('Envoi interrompu avant réponse. Aucune action n’est déclarée effectuée.');
        resetOrb();
      } else {
        setSendError(errorMessage(cause));
        notifyApiError(cause);
      }
    } finally {
      setSending(false);
      abortRef.current = null;
      setMicActive(false);
    }
  };

  const handleCopy = async (message: Message): Promise<void> => {
    try {
      await navigator.clipboard.writeText(message.content);
      setNotice('Message copié dans le presse-papiers.');
    } catch {
      setNotice('Copie impossible : le navigateur a refusé l’accès au presse-papiers.');
    }
  };

  const retry = (assistantMessage: Message): void => {
    const index = messages.findIndex((message) => message.id === assistantMessage.id);
    const previousUser = messages
      .slice(0, index < 0 ? messages.length : index)
      .reverse()
      .find((message) => message.role === 'user');
    if (!previousUser) {
      setNotice('Aucun message utilisateur à relancer.');
      return;
    }
    void sendMessage(previousUser.content);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="page-head__eyebrow">Conversation</span>
          <h1 style={{ fontSize: '1.6rem' }}>{title}</h1>
        </div>
        <div className="row">
          {conversation?.is_demo ? <span className="badge badge--demo">[DEMO]</span> : null}
          <a className="btn btn--soft" href={href({ name: 'conversations' })}>
            <Icon name="history" size={16} />
            Historique
          </a>
          <button type="button" className="btn" onClick={() => navigate({ name: 'chat' })}>
            <Icon name="plus" size={16} />
            Nouveau
          </button>
        </div>
      </div>

      <div className="chat">
        <aside className="chat-rail" aria-label="Conversations récentes">
          <div className="chat-rail__head">
            <strong style={{ fontSize: '0.8125rem' }}>Récentes</strong>
            <a className="meta" href={href({ name: 'conversations' })}>
              Tout voir
            </a>
          </div>
          <div className="chat-rail__list">
            {conversationsError ? <p className="meta">{conversationsError}</p> : null}
            {conversations.length === 0 && !conversationsError ? (
              <p className="meta">Aucune conversation enregistrée.</p>
            ) : null}
            {conversations.slice(0, 30).map((item) => (
              <a
                key={item.id}
                className="rail-item"
                href={href({ name: 'chat', conversationId: item.id })}
                aria-current={item.id === conversationId ? 'page' : undefined}
              >
                <span className="rail-item__title">{item.title?.trim() || 'Sans titre'}</span>
                <span className="rail-item__meta">{formatRelative(item.updated_at)}</span>
              </a>
            ))}
          </div>
        </aside>

        <section className="chat-main" aria-label="Fil de conversation">
          <header className="chat-head">
            <div className="chat-head__title">
              <h2>{title}</h2>
              <p className="meta">
                {conversationId ? `ID ${truncate(conversationId, 18)}` : 'Nouvelle conversation'}
                {conversation?.status ? ` · ${conversation.status}` : ''}
              </p>
            </div>
            <span
              className={`badge badge--${connection === 'online' ? 'success' : 'warning'}`}
              title="Le WebSocket n’est pas la source de vérité : reconnexion et récupération REST automatiques."
            >
              {connection === 'online' ? 'Temps réel' : 'REST uniquement'}
            </span>
          </header>

          <div className="thread" aria-live="polite" aria-busy={sending}>
            {loadingMessages && messages.length === 0 ? (
              <div className="stack" aria-hidden="true">
                <div className="skeleton skeleton--block" />
                <div className="skeleton skeleton--block" style={{ width: '70%' }} />
              </div>
            ) : null}

            {messagesError ? (
              <p className="notice notice--warning" role="alert">
                <Icon name="alert" size={16} />
                <span>
                  Historique indisponible : {messagesError}{' '}
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => setMessagesNonce((value) => value + 1)}
                  >
                    Réessayer
                  </button>
                </span>
              </p>
            ) : null}

            {!loadingMessages && messages.length === 0 && !messagesError ? (
              <div style={{ margin: 'auto', width: '100%', maxWidth: 520 }} className="chat-empty">
                <div className="orb-hero" style={{ paddingTop: 0 }}>
                  <HybridOrb state={orbState} className="orb--compact" />
                </div>
                <EmptyState title="Commencez par un objectif" icon={<Icon name="spark" size={24} />}>
                  Décrivez ce que vous voulez accomplir. Kwes confirme, planifie, puis exécute avec
                  votre validation pour les actions sensibles.
                </EmptyState>
                <div className="row" style={{ justifyContent: 'center', marginTop: 12 }}>
                  {[
                    'Explique ce que tu peux faire et tes limites.',
                    'Prépare un plan de lancement en 5 étapes.',
                    'Résume mes missions en cours.',
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      className="filter"
                      onClick={() => setDraft(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
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
              <article className="msg msg--assistant" aria-label="Message de Kwes en cours d’affichage">
                <div className="msg__who">
                  <span>Kwes</span>
                  <span className="badge badge--accent">affichage local</span>
                </div>
                <div className="msg__bubble">
                  {typing.message.content.slice(0, typing.shown)}
                  <span className="typing" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </article>
            ) : null}

            {streaming ? (
              <article className="msg msg--assistant" aria-label="Réponse en streaming">
                <div className="msg__who">
                  <span>Kwes</span>
                  <span className="badge badge--accent">en direct</span>
                </div>
                <div className="msg__bubble">
                  {streaming}
                  <span className="typing" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </article>
            ) : null}

            {sending && !streaming && !typing ? (
              <p className="typing" role="status">
                <i />
                <i />
                <i />
                <span style={{ marginLeft: 8 }}>Kwes traite votre demande…</span>
              </p>
            ) : null}

            <div ref={bottomRef} />
          </div>

          <div className="chat-compose">
            {sendError ? (
              <p className="notice notice--danger" role="alert" style={{ marginBottom: 10 }}>
                {sendError} — votre message a été replacé dans le brouillon.
              </p>
            ) : null}
            {notice ? (
              <p className="notice notice--info" role="status" style={{ marginBottom: 10 }}>
                {notice}
              </p>
            ) : null}
            {connection === 'offline' ? (
              <p className="notice notice--warning" style={{ marginBottom: 10 }}>
                <Icon name="alert" size={16} />
                <span>
                  Connexion temps réel perdue. Envois via REST et affichage progressif local ;
                  reconnexion automatique.
                </span>
              </p>
            ) : null}

            <Composer
              value={draft}
              onChange={setDraft}
              onSubmit={() => {
                void sendMessage(draft);
              }}
              busy={sending}
              onStop={() => abortRef.current?.abort()}
              micAllowed={prefs.voiceEnabled}
              autoFocus
              placeholder={conversationId ? 'Poursuivre la conversation…' : 'Décrivez votre objectif…'}
              hint="Entrée pour envoyer · POST /chat réel · brouillon local conservé"
            />
            {sourcesLabel(messages.at(-1)?.metadata) ? (
              <p className="meta" style={{ marginTop: 6 }}>
                Mission liée : {sourcesLabel(messages.at(-1)?.metadata)}
              </p>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}
