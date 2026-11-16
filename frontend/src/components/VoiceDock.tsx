import { useEffect, useRef, useState } from 'react';
import '../styles/voice.css';
import { Icon } from './Icon';
import { HybridOrb } from './orb/HybridOrb';
import { orbStateFor, voiceAnnouncement, voiceStatusLabel, type VoicePhase } from '../lib/voice-session';
import type { VoiceConversation } from '../lib/use-voice-conversation';

interface VoiceDockProps {
  voice: VoiceConversation;
  /** Préférence utilisateur (Réglages) : coupe entièrement l'accès micro. */
  enabled: boolean;
  /** Message technique à afficher sous le dock (erreur d'envoi, repli…). */
  notice?: string | null;
}

const PHASE_HINT: Record<VoicePhase, string> = {
  idle: 'Micro coupé',
  listening: 'À vous',
  thinking: 'Kwes réfléchit',
  speaking: 'Kwes parle',
};

/**
 * Dock du mode vocal continu. Le bouton micro est le seul point d'entrée :
 * aucun accès au microphone ni lecture audio avant ce clic explicite.
 */
export function VoiceDock({ voice, enabled, notice }: VoiceDockProps) {
  const [opened, setOpened] = useState(false);
  const label = voiceStatusLabel(voice);

  // Annonce discrète : uniquement quand l'état change réellement (jamais la transcription).
  const announcement = voiceAnnouncement(voice);
  const [live, setLive] = useState('');
  const previous = useRef('');
  useEffect(() => {
    if (announcement === previous.current) return;
    previous.current = announcement;
    setLive(announcement);
  }, [announcement]);

  if (!enabled) return null;

  if (!voice.supported) {
    return (
      <section className="voice-dock voice-dock--unsupported" aria-labelledby="kwes-voice-title">
        <div className="voice-dock__head">
          <span className="voice-dock__icon" aria-hidden="true">
            <Icon name="mic-off" size={18} />
          </span>
          <div>
            <h2 className="voice-dock__title" id="kwes-voice-title">
              Mode vocal indisponible
            </h2>
            <p className="voice-dock__hint">
              Ce navigateur ne fournit pas de reconnaissance vocale (Web Speech API absente).
              La saisie texte reste pleinement fonctionnelle — envoyez vos messages depuis le
              champ ci-dessous.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      className={`voice-dock${voice.active ? ' is-active' : ''}`}
      data-phase={voice.phase}
      aria-labelledby="kwes-voice-title"
    >
      <div className="voice-dock__head">
        <div className="voice-dock__orb" aria-hidden="true">
          <HybridOrb state={orbStateFor(voice.phase)} />
        </div>

        <div className="voice-dock__body">
          <h2 className="voice-dock__title" id="kwes-voice-title">
            Conversation vocale
          </h2>
          <p className="voice-dock__status" id="kwes-voice-status">
            <span className={`voice-dock__dot voice-dock__dot--${voice.phase}`} aria-hidden="true" />
            {voice.active ? label : 'Désactivé — activez le micro pour parler.'}
          </p>

          {voice.active && voice.pending ? (
            <p className="voice-dock__transcript" title="Transcription en cours">
              « {voice.pending} »
            </p>
          ) : null}

          <div className="voice-dock__actions">
            <button
              type="button"
              className={`btn voice-dock__mic${voice.active ? ' is-listening' : ''}`}
              aria-pressed={voice.active}
              aria-label={voice.active ? 'Couper le mode vocal' : 'Activer le mode vocal'}
              aria-describedby="kwes-voice-status kwes-voice-help"
              onClick={voice.toggle}
            >
              <Icon name={voice.active ? 'mic-off' : 'mic'} size={18} />
              {voice.active ? 'Couper le micro' : 'Parler à Kwes'}
            </button>

            <button
              type="button"
              className="btn btn--ghost btn--sm"
              aria-pressed={voice.standby}
              aria-label="Mode veille : n'écouter que le mot d'activation Kwes"
              disabled={!voice.active}
              onClick={() => voice.setStandby(!voice.standby)}
            >
              <Icon name="spark" size={14} />
              Veille « Kwes »
            </button>

            <button
              type="button"
              className="btn btn--ghost btn--sm"
              aria-expanded={opened}
              aria-controls="kwes-voice-help"
              onClick={() => setOpened((value) => !value)}
            >
              {opened ? 'Masquer' : 'Comment ça marche'}
            </button>
          </div>

          <p className="voice-dock__hint" id="kwes-voice-help" hidden={!opened}>
            Parlez normalement : Kwes envoie votre phrase après 1,2 s de silence. En mode veille,
            dites « Kwes » ou « Hey Kwes » pour l'activer sans clic. Pendant la réponse, parlez
            pour l'interrompre (barge-in). La dictée utilise le service de reconnaissance du
            navigateur ; le texte peut donc transiter par son fournisseur.
          </p>

          <p className="voice-dock__phase" aria-hidden="true">
            {voice.active ? PHASE_HINT[voice.phase] : PHASE_HINT.idle}
          </p>
        </div>
      </div>

      {notice ? (
        <p className="voice-dock__notice" role="status">
          {notice}
        </p>
      ) : null}

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {live}
      </p>
    </section>
  );
}
