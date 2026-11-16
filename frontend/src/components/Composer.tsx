import { useEffect, useRef } from 'react';
import { useDictation } from '../lib/speech';
import { useKwes } from '../state/KwesProvider';
import { Icon } from './Icon';

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy?: boolean;
  disabled?: boolean;
  placeholder?: string;
  onStop?: () => void;
  autoFocus?: boolean;
  micAllowed?: boolean;
  hint?: string;
}

export function Composer({
  value,
  onChange,
  onSubmit,
  busy = false,
  disabled = false,
  placeholder = 'Écrivez à Kwes…',
  onStop,
  autoFocus = false,
  micAllowed = true,
  hint,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { setMicActive } = useKwes();

  const dictation = useDictation({
    onTranscript: (text) => {
      onChange(value ? `${value.trimEnd()} ${text}` : text);
    },
    onStart: () => setMicActive(true),
    onEnd: () => setMicActive(false),
  });

  // Ajuste la hauteur du textarea au contenu.
  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const canSubmit = value.trim().length > 0 && !busy && !disabled;
  const micDisabled = !micAllowed || !dictation.supported || busy || disabled;

  return (
    <div>
      <div className="composer">
        <label className="sr-only" htmlFor="kwes-composer">
          Message pour Kwes
        </label>
        <textarea
          id="kwes-composer"
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (canSubmit) onSubmit();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          aria-describedby="kwes-composer-hint"
        />
        {micAllowed ? (
          <button
            type="button"
            className="btn btn--icon"
            aria-label={dictation.listening ? 'Arrêter la dictée' : 'Dicter le message'}
            aria-pressed={dictation.listening}
            title={
              dictation.supported
                ? dictation.listening
                  ? 'Arrêter la dictée'
                  : 'Dicter le message'
                : 'Reconnaissance vocale non prise en charge par ce navigateur'
            }
            onClick={() => {
              if (dictation.listening) {
                dictation.stop();
                setMicActive(false);
              } else {
                dictation.start();
              }
            }}
            disabled={micDisabled}
          >
            <Icon name={dictation.listening ? 'mic-off' : 'mic'} size={18} />
          </button>
        ) : null}
        {busy && onStop ? (
          <button type="button" className="btn btn--danger" onClick={onStop}>
            <Icon name="stop" size={16} />
            Arrêter
          </button>
        ) : (
          <button type="button" className="btn btn--primary" onClick={onSubmit} disabled={!canSubmit} aria-label="Envoyer le message">
            <Icon name="send" size={16} />
            <span className="composer__send-label">Envoyer</span>
          </button>
        )}
      </div>
      <div className="composer__hint" id="kwes-composer-hint">
        <span>{hint ?? 'Entrée pour envoyer · Maj+Entrée pour un retour à la ligne'}</span>
        <span>{value.length.toLocaleString('fr-FR')} car.</span>
      </div>
      {dictation.listening ? (
        <p className="notice notice--info" role="status" style={{ marginTop: 8 }}>
          Micro actif — dictez votre message, il s’ajoutera au brouillon.
        </p>
      ) : null}
      {dictation.error ? (
        <p className="notice notice--warning" role="status" style={{ marginTop: 8 }}>
          {dictation.error}
        </p>
      ) : null}
      {micAllowed && !dictation.supported ? (
        <p className="meta" style={{ marginTop: 6 }}>
          Dictée indisponible dans ce navigateur ; le texte reste pleinement fonctionnel.
        </p>
      ) : null}
    </div>
  );
}
