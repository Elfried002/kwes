import { formatTime } from '../lib/format';
import { isRecord, type Message } from '../lib/types';
import { Icon } from './Icon';

interface MessageBubbleProps {
  message: Message;
  onCopy: (message: Message) => void;
  onRetry?: (message: Message) => void;
  streaming?: boolean;
}

const ROLE_LABELS: Record<string, string> = {
  user: 'Vous',
  assistant: 'Kwes',
  tool: 'Outil',
  system: 'Système',
};

interface SourceItem {
  title: string;
  url?: string;
}

function readSources(metadata: Record<string, unknown> | null | undefined): SourceItem[] {
  if (!metadata) return [];
  const raw = metadata.sources;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item): SourceItem | null => {
      if (typeof item === 'string') return { title: item };
      if (isRecord(item)) {
        const title = typeof item.title === 'string' ? item.title : typeof item.url === 'string' ? item.url : null;
        if (!title) return null;
        return { title, url: typeof item.url === 'string' ? item.url : undefined };
      }
      return null;
    })
    .filter((item): item is SourceItem => item !== null)
    .slice(0, 5);
}

export function MessageBubble({ message, onCopy, onRetry, streaming = false }: MessageBubbleProps) {
  const metadata = message.metadata ?? null;
  const demo = message.is_demo === true || metadata?.is_demo === true;
  const simulated = metadata?.simulated === true;
  const sources = readSources(metadata);
  const roleLabel = ROLE_LABELS[message.role] ?? message.role;

  return (
    <article className={`msg msg--${message.role}`} aria-label={`Message de ${roleLabel}`}>
      <div className="msg__who">
        <span>{roleLabel}</span>
        {demo ? <span className="badge badge--demo">[DEMO]</span> : null}
        <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
      </div>
      <div className="msg__bubble">
        {message.content}
        {streaming ? <span className="typing" aria-hidden="true"><i /><i /><i /></span> : null}
      </div>

      {simulated ? (
        <p className="meta">Affichage progressif local — WebSocket indisponible, contenu final reçu par REST.</p>
      ) : null}

      {sources.length > 0 ? (
        <div className="msg__foot" style={{ flexWrap: 'wrap' }}>
          <span className="meta">Sources :</span>
          {sources.map((source) =>
            source.url ? (
              <a key={`${source.title}-${source.url}`} className="meta" href={source.url} target="_blank" rel="noreferrer noopener">
                {source.title}
              </a>
            ) : (
              <span key={source.title} className="meta">
                {source.title}
              </span>
            ),
          )}
        </div>
      ) : null}

      <div className="msg__foot">
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => onCopy(message)}>
          <Icon name="copy" size={12} />
          Copier
        </button>
        {onRetry && message.role === 'assistant' ? (
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => onRetry(message)}>
            <Icon name="refresh" size={12} />
            Recommencer
          </button>
        ) : null}
      </div>
    </article>
  );
}
