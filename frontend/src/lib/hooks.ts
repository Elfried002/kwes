import { useCallback, useEffect, useRef, useState } from 'react';

/** Respecte `prefers-reduced-motion` et se met à jour si le réglage change. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (event: MediaQueryListEvent): void => setReduced(event.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  return reduced;
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} — Kwes` : 'Kwes — Personal Autonomous AI Agent';
  }, [title]);
}

export interface AsyncResource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Chargement REST avec annulation. `deps` doit garder une longueur stable.
 * `refreshKey` permet de rejouer la requête (reconnexion WS, action utilisateur).
 */
export function useApi<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean; refreshKey?: number } = {},
): AsyncResource<T> {
  const { enabled = true, refreshKey = 0 } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(enabled);
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);

    loaderRef
      .current(controller.signal)
      .then((result) => {
        if (!active) return;
        setData(result);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(cause);
        setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, refreshKey, nonce, ...deps]);

  return { data, error, loading, reload };
}

/** Horloge légère pour les libellés relatifs / compte à rebours. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
