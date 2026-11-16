import { useState } from 'react';
import { downloadDocument, errorMessage } from '../lib/api';
import { formatTime } from '../lib/format';
import { isRecord, type Message } from '../lib/types';
import { Icon } from './Icon';

interface MessageBubbleProps {
  message: Message;
  onCopy: (message: Message) => void;
  onRetry?: (message: Message) => void;
  streaming?: boolean;
}

interface SourceItem {
  title: string;
  url?: string;
}

interface DocumentItem {
  id: string;
  label: string;
}

/** Documents produits pendant ce tour (outil `document_write` exécuté). */
function readDocuments(metadata: Record<string, unknown> | null | undefined): DocumentItem[] {
  if (!metadata) return [];
  const tools = metadata.tools;
  if (!Array.isArray(tools)) return [];
  return tools
    .map((tool): DocumentItem | null => {
      if (!isRecord(tool)) return null;
      if (tool.name !== 'document_write' || tool.status !== 'executed') return null;
      if (tool.reference_type !== 'document' || typeof tool.reference !== 'string') return null;
      return {
        id: tool.reference,
        label: typeof tool.label === 'string' && tool.label ? tool.label : 'Ouvrir le document',
      };
    })
    .filter((item): item is DocumentItem => item !== null);
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

/**
 * Un tour de parole : bulle simple, horodatage discret, actions au survol.
 * Aucun cadre autour des réponses de Kwes — seul le message de l'utilisateur
 * porte un fond contrasté.
 */
export function MessageBubble({ message, onCopy, onRetry, streaming = false }: MessageBubbleProps) {
  const sources = readSources(message.metadata ?? null);
  const documents = readDocuments(message.metadata ?? null);
  const isAssistant = message.role === 'assistant';
  const [busyDocument, setBusyDocument] = useState<string | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);

  async function openDocument(id: string): Promise<void> {
    setBusyDocument(id);
    setDocumentError(null);
    try {
      const file = await downloadDocument(id);
      const url = URL.createObjectURL(file.blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = file.filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) {
      setDocumentError(errorMessage(error));
    } finally {
      setBusyDocument(null);
    }
  }

  return (
    <article
      className={`turn turn--${message.role}`}
      aria-label={isAssistant ? 'Réponse de Kwes' : 'Votre message'}
    >
      <div className="turn__bubble">
        {message.content}
        {streaming ? <span className="turn__caret" aria-hidden="true" /> : null}
      </div>

      {sources.length > 0 ? (
        <p className="turn__sources">
          <span>Sources</span>
          {sources.map((source) =>
            source.url ? (
              <a key={`${source.title}-${source.url}`} href={source.url} target="_blank" rel="noreferrer noopener">
                {source.title}
              </a>
            ) : (
              <span key={source.title}>{source.title}</span>
            ),
          )}
        </p>
      ) : null}

      {documents.length > 0 ? (
        <p className="turn__documents">
          {documents.map((item) => (
            <button
              key={item.id}
              type="button"
              className="turn__document"
              onClick={() => void openDocument(item.id)}
              disabled={busyDocument === item.id}
            >
              <Icon name="file" size={14} />
              {busyDocument === item.id ? 'Ouverture…' : item.label}
            </button>
          ))}
        </p>
      ) : null}
      {documentError ? (
        <p className="turn__document-error" role="alert">
          {documentError}
        </p>
      ) : null}

      <div className="turn__meta">
        <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
        <span className="turn__actions">
          <button
            type="button"
            className="turn__action"
            onClick={() => onCopy(message)}
            aria-label="Copier le message"
            title="Copier"
          >
            <Icon name="copy" size={14} />
          </button>
          {isAssistant && onRetry ? (
            <button
              type="button"
              className="turn__action"
              onClick={() => onRetry(message)}
              aria-label="Recommencer cette réponse"
              title="Recommencer"
            >
              <Icon name="refresh" size={14} />
            </button>
          ) : null}
        </span>
      </div>
    </article>
  );
}
