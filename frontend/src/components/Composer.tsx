import { useEffect, useRef, useState } from 'react';
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
  /** Bascule « Analyser » : affichée seulement si fournie (accueil). */
  analysis?: { active: boolean; onToggle: () => void };
  /** Ouvre la conversation vocale immersive. Fourni = barre d'accueil complète. */
  onVoice?: () => void;
  /** Incrémenté par l'écran pour remettre le curseur dans le champ. */
  focusSignal?: number;
  /** Précision lue par les lecteurs d'écran sous le champ. */
  hint?: string;
}

/**
 * Une seule barre de saisie, façon ChatGPT : pièce jointe, champ qui grandit,
 * bascule « Analyser », dictée, et le bouton bleu qui ouvre la voix immersive.
 * Entrée envoie, Maj+Entrée revient à la ligne.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  busy = false,
  disabled = false,
  placeholder = 'Demander à Kwes',
  onStop,
  autoFocus = false,
  micAllowed = true,
  analysis,
  onVoice,
  focusSignal,
  hint,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [attachNotice, setAttachNotice] = useState<string | null>(null);
  const { setMicActive } = useKwes();

  const dictation = useDictation({
    lang: 'fr-FR',
    onTranscript: (text) => {
      const current = value.trimEnd();
      onChange(current ? `${current} ${text}` : text);
      textareaRef.current?.focus();
    },
    onStart: () => setMicActive(true),
    onEnd: () => setMicActive(false),
  });

  // Hauteur du champ ajustée au contenu (une ligne au départ, 6 lignes au plus).
  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 168)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (focusSignal === undefined) return;
    textareaRef.current?.focus();
  }, [focusSignal]);

  useEffect(() => {
    if (!attachNotice) return;
    const timer = window.setTimeout(() => setAttachNotice(null), 7000);
    return () => window.clearTimeout(timer);
  }, [attachNotice]);

  const canSubmit = value.trim().length > 0 && !busy && !disabled;
  const micDisabled = !micAllowed || !dictation.supported || busy || disabled;
  const immersive = Boolean(onVoice);

  const submit = (): void => {
    if (!canSubmit) return;
    setAttachNotice(null);
    if (dictation.listening) dictation.stop();
    onSubmit();
  };

  return (
    <div className={`composer composer--bar${busy ? ' is-busy' : ''}${immersive ? ' composer--immersive' : ''}`}>
      <div className="composer__row">
        <input
          ref={fileRef}
          type="file"
          className="composer__file"
          tabIndex={-1}
          aria-hidden="true"
          onChange={() => {
            setAttachNotice(
              'L’envoi de fichiers n’est pas encore disponible. Décrivez votre document dans le message.',
            );
            if (fileRef.current) fileRef.current.value = '';
          }}
        />
        <button
          type="button"
          className="composer__tool"
          aria-label="Joindre un fichier"
          title="Joindre un fichier — l’envoi de fichiers n’est pas encore disponible"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
        >
          <Icon name="plus" size={21} />
        </button>

        <label className="sr-only" htmlFor="kwes-composer">
          Message pour Kwes
        </label>
        <textarea
          id="kwes-composer"
          ref={textareaRef}
          className="composer__field"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          title="Entrée pour envoyer · Maj+Entrée pour revenir à la ligne"
          enterKeyHint="send"
          disabled={disabled}
          rows={1}
          aria-describedby="kwes-composer-hint"
        />

        <div className="composer__tools">
          {busy && onStop ? (
            <button
              type="button"
              className="composer__chip composer__chip--stop"
              onClick={onStop}
              aria-label="Arrêter la réponse en cours"
            >
              <Icon name="stop" size={14} />
              <span>Arrêter</span>
            </button>
          ) : analysis ? (
            <button
              type="button"
              className="composer__chip"
              aria-pressed={analysis.active}
              aria-label="Analyser : demander une réponse approfondie"
              title="Analyser — Kwes planifie les étapes avant de répondre"
              onClick={analysis.onToggle}
              disabled={busy || disabled}
            >
              <Icon name="spark" size={16} />
              <span>Analyser</span>
            </button>
          ) : null}

          {micAllowed ? (
            <button
              type="button"
              className="composer__tool"
              aria-label={dictation.listening ? 'Arrêter la dictée' : 'Dicter le message'}
              aria-pressed={dictation.listening}
              title={
                dictation.supported
                  ? dictation.listening
                    ? 'Arrêter la dictée'
                    : 'Dicter le message'
                  : 'La dictée n’est pas prise en charge par ce navigateur'
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
              <Icon name={dictation.listening ? 'mic-off' : 'mic'} size={19} />
            </button>
          ) : null}

          {onVoice ? (
            <button
              type="button"
              className="composer__voice"
              onClick={onVoice}
              aria-label="Ouvrir la conversation vocale"
              title="Parler à Kwes à voix haute"
            >
              <Icon name="waveform" size={20} />
            </button>
          ) : (
            <button
              type="button"
              className="composer__send"
              onClick={submit}
              disabled={!canSubmit}
              aria-label="Envoyer le message"
              title="Envoyer"
            >
              <Icon name="send" size={17} />
            </button>
          )}
        </div>
      </div>

      <p className="sr-only" id="kwes-composer-hint">
        {hint ?? 'Entrée pour envoyer, Maj+Entrée pour revenir à la ligne.'}
      </p>

      {dictation.listening ? (
        <p className="composer__status" role="status">
          Micro actif : dictez votre message, il s’ajoute au champ.
        </p>
      ) : null}
      {attachNotice ? (
        <p className="composer__status" role="status">
          {attachNotice}
        </p>
      ) : null}
      {dictation.error ? (
        <p className="composer__status composer__status--warning" role="status">
          {dictation.error}
        </p>
      ) : null}
    </div>
  );
}
