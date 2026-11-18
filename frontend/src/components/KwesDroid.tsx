import { useEffect, useRef } from 'react';
import type { OrbState } from './orb/orb-state-machine';
import './kwes-droid.css';

type KwesDroidProps = {
  phase: OrbState;
  levelRef?: React.RefObject<number>;
  className?: string;
};

/**
 * Kwes — droïde vivant.
 *
 * Compromis des trois références :
 *  - coque claire et visage-écran sombre, grands yeux cyan (réf. 3),
 *  - halo lumineux et expressivité émotionnelle (réf. 2),
 *  - corps flottant, mains détachées, dégradé violet/bleu (réf. 1).
 *
 * Le personnage ne « joue » pas un état inventé : `phase` vient de la machine à
 * états (événements réels), `levelRef` du niveau audio mesuré. Aucun état n'est
 * déduit du texte du modèle.
 */
export function KwesDroid({ phase, levelRef, className }: KwesDroidProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Le niveau audio est écrit dans une variable CSS, sans re-render React.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const level = Math.max(0, Math.min(1, Number(levelRef?.current) || 0));
      if (rootRef.current) {
        rootRef.current.style.setProperty('--level', level.toFixed(3));
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [levelRef]);

  return (
    <div
      ref={rootRef}
      className={`kwes-droid${className ? ` ${className}` : ''}`}
      data-phase={phase}
      role="img"
      aria-label={ARIA[phase] ?? 'Kwes'}
    >
      <svg viewBox="0 0 240 280" className="kwes-droid__svg" aria-hidden="true">
        <defs>
          <linearGradient id="kd-shell" x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="62%" stopColor="#e8ecf6" />
            <stop offset="100%" stopColor="#c9d2e6" />
          </linearGradient>
          <linearGradient id="kd-glass" x1="0.1" y1="0" x2="0.9" y2="1">
            <stop offset="0%" stopColor="#16213c" />
            <stop offset="55%" stopColor="#0d1526" />
            <stop offset="100%" stopColor="#070c16" />
          </linearGradient>
          <linearGradient id="kd-halo" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#8b7bff" />
            <stop offset="50%" stopColor="#5ce1ff" />
            <stop offset="100%" stopColor="#8b7bff" />
          </linearGradient>
          <radialGradient id="kd-glow" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0%" stopColor="#5ce1ff" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#5ce1ff" stopOpacity="0" />
          </radialGradient>
          <filter id="kd-soft" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>

        {/* halo orbital */}
        <g className="kwes-droid__halo">
          <ellipse cx="120" cy="44" rx="72" ry="15" fill="none" stroke="url(#kd-halo)" strokeWidth="12" opacity="0.28" filter="url(#kd-soft)" />
          <ellipse cx="120" cy="44" rx="72" ry="15" fill="none" stroke="url(#kd-halo)" strokeWidth="3.5" opacity="0.85" />
          <ellipse cx="120" cy="44" rx="72" ry="15" fill="none" stroke="#ffffff" strokeWidth="1" opacity="0.35" />
        </g>

        <g className="kwes-droid__float">
          {/* ombre au sol */}
          <ellipse className="kwes-droid__shadow" cx="120" cy="264" rx="52" ry="9" fill="#0b1020" opacity="0.18" />

          {/* corps */}
          <g className="kwes-droid__body">
            <rect x="92" y="176" width="56" height="52" rx="24" fill="url(#kd-shell)" />
            <rect x="104" y="196" width="32" height="12" rx="6" fill="#b9c5dd" opacity="0.75" />
            <circle className="kwes-droid__core" cx="120" cy="219" r="4.5" fill="#5ce1ff" />
          </g>

          {/* mains flottantes */}
          <ellipse className="kwes-droid__hand kwes-droid__hand--l" cx="76" cy="196" rx="11" ry="15" fill="url(#kd-shell)" />
          <ellipse className="kwes-droid__hand kwes-droid__hand--r" cx="164" cy="196" rx="11" ry="15" fill="url(#kd-shell)" />

          {/* tête */}
          <g className="kwes-droid__head">
            <rect x="58" y="58" width="124" height="112" rx="44" fill="url(#kd-shell)" />
            <rect x="66" y="66" width="108" height="96" rx="38" fill="url(#kd-glass)" />

            {/* reflet vitre */}
            <path d="M78 78c14-10 42-12 58-8-18 2-38 8-52 18z" fill="#ffffff" opacity="0.14" />

            {/* antenne */}
            <g className="kwes-droid__antenna">
              <line x1="120" y1="58" x2="120" y2="50" stroke="#c9d2e6" strokeWidth="4" strokeLinecap="round" />
              <circle cx="120" cy="47" r="4" fill="#5ce1ff" />
            </g>

            {/* visage */}
            <g className="kwes-droid__face">
              <g className="kwes-droid__eye kwes-droid__eye--l">
                <ellipse cx="99" cy="112" rx="9" ry="13" fill="#5ce1ff" />
                <ellipse cx="96" cy="106" rx="3" ry="4" fill="#ffffff" opacity="0.75" />
              </g>
              <g className="kwes-droid__eye kwes-droid__eye--r">
                <ellipse cx="141" cy="112" rx="9" ry="13" fill="#5ce1ff" />
                <ellipse cx="138" cy="106" rx="3" ry="4" fill="#ffffff" opacity="0.75" />
              </g>
              <path
                className="kwes-droid__mouth"
                d="M108 138c4 5 20 5 24 0"
                fill="none"
                stroke="#5ce1ff"
                strokeWidth="4"
                strokeLinecap="round"
              />
            </g>

            {/* oreilles */}
            <rect x="48" y="100" width="10" height="28" rx="5" fill="#c9d2e6" />
            <rect x="182" y="100" width="10" height="28" rx="5" fill="#c9d2e6" />
          </g>

          {/* bulle de réflexion */}
          <g className="kwes-droid__bubble">
            <circle cx="176" cy="46" r="4" fill="#5ce1ff" opacity="0.6" />
            <circle cx="188" cy="34" r="6" fill="#5ce1ff" opacity="0.75" />
            <circle cx="202" cy="22" r="13" fill="#e9f7ff" opacity="0.92" />
            <text x="202" y="27" textAnchor="middle" fontSize="14" fontWeight="700" fill="#0d1526">?</text>
          </g>

          {/* anneau d'exécution */}
          <g className="kwes-droid__orbit">
            <circle cx="120" cy="114" r="74" fill="none" stroke="#5ce1ff" strokeWidth="2" strokeDasharray="6 14" opacity="0.55" />
            <circle cx="120" cy="40" r="4" fill="#5ce1ff" />
          </g>

          {/* pastille d'approbation */}
          <g className="kwes-droid__badge">
            <circle cx="176" cy="196" r="13" fill="#ffcf6b" />
            <rect x="173" y="190" width="3" height="8" rx="1.5" fill="#3a2a00" />
            <rect x="179" y="190" width="3" height="8" rx="1.5" fill="#3a2a00" />
          </g>
        </g>
      </svg>
    </div>
  );
}

const ARIA: Record<string, string> = {
  idle: 'Kwes, au repos',
  listening: 'Kwes vous écoute',
  thinking: 'Kwes réfléchit',
  executing: 'Kwes exécute une tâche',
  speaking: 'Kwes parle',
  response: 'Kwes répond',
  success: 'Kwes a terminé',
  error: 'Kwes a rencontré une erreur',
  waiting_approval: 'Kwes attend votre approbation',
};
