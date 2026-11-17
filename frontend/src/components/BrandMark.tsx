import type { OrbState } from './orb/orb-state-machine';

/**
 * Marque de Kwes : la tête du droïde.
 *
 * Le logo est unique dans toute l'application (en-tête, site public, connexion,
 * favicon). L'état vient de la machine à états réelle ; seule la lueur change,
 * jamais le dessin. `prefers-reduced-motion` coupe l'animation.
 */
export function BrandMark({
  size = 38,
  state = 'idle',
  className,
}: {
  size?: number;
  state?: OrbState;
  className?: string;
}) {
  return (
    <span
      className={`brand-droid ${className ?? ''}`}
      data-state={state}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <img src="/brand/droid-head.svg" alt="" width={size} height={size} draggable={false} />
    </span>
  );
}
