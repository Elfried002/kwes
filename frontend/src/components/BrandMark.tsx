import type { OrbState } from './orb/orb-state-machine';

/**
 * Marque animée de Kwes.
 *
 * Reprend en miniature l'anneau et les particules de l'Orb : deux anneaux qui
 * tournent lentement autour d'un cœur lumineux, trois particules en orbite.
 * Uniquement `transform`/`opacity`, aucune image animée, et tout s'immobilise
 * avec `prefers-reduced-motion`.
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
      className={`brand-orb ${className ?? ''}`}
      data-state={state}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span className="brand-orb__halo" />
      <span className="brand-orb__ring brand-orb__ring--outer" />
      <span className="brand-orb__ring brand-orb__ring--inner" />
      <span className="brand-orb__core" />
      <span className="brand-orb__particle brand-orb__particle--1" />
      <span className="brand-orb__particle brand-orb__particle--2" />
      <span className="brand-orb__particle brand-orb__particle--3" />
    </span>
  );
}
