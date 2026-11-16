import { useKwes } from '../state/KwesProvider';

export function OrbStatus({ showCaption = false }: { showCaption?: boolean }) {
  const { orbState, orbMeta, lastDetail } = useKwes();
  return (
    <div className="stack--sm" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <p className="orb-status" data-state={orbState}>
        <span className="orb-status__dot" aria-hidden="true" />
        <span>
          Kwes · <strong style={{ fontWeight: 620 }}>{orbMeta.label}</strong>
        </span>
      </p>
      {showCaption ? (
        <p className="orb-hero__hint">{lastDetail ?? orbMeta.caption}</p>
      ) : null}
    </div>
  );
}
