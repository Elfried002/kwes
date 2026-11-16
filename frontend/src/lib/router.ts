import { useSyncExternalStore } from 'react';

export type AuthMode = 'signin' | 'signup' | 'reset';

export type Route =
  | { name: 'home' }
  | { name: 'auth'; mode: AuthMode }
  | { name: 'chat'; conversationId?: string }
  | { name: 'voice' }
  | { name: 'conversations' }
  | { name: 'tasks' }
  | { name: 'task'; id: string }
  | { name: 'approvals' }
  | { name: 'settings' };

export const HOME: Route = { name: 'home' };

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#\/?/, '').split('?')[0] ?? '';
  const segments = raw.split('/').filter(Boolean).map((segment) => decodeURIComponent(segment));
  const [head, second] = segments;

  switch (head) {
    case undefined:
    case '':
      return { name: 'home' };
    case 'connexion':
    case 'login':
      return { name: 'auth', mode: 'signin' };
    case 'inscription':
    case 'signup':
      return { name: 'auth', mode: 'signup' };
    case 'mot-de-passe-oublie':
      return { name: 'auth', mode: 'reset' };
    case 'chat':
      return second ? { name: 'chat', conversationId: second } : { name: 'chat' };
    case 'parler':
    case 'voix':
      return { name: 'voice' };
    case 'conversations':
      return { name: 'conversations' };
    case 'tasks':
      return second ? { name: 'task', id: second } : { name: 'tasks' };
    case 'activity':
      return second ? { name: 'task', id: second } : { name: 'tasks' };
    case 'approvals':
      return { name: 'approvals' };
    case 'settings':
      return { name: 'settings' };
    default:
      return { name: 'home' };
  }
}

export function routeToPath(route: Route): string {
  switch (route.name) {
    case 'home':
      return '/';
    case 'auth':
      return route.mode === 'signup'
        ? '/inscription'
        : route.mode === 'reset'
          ? '/mot-de-passe-oublie'
          : '/connexion';
    case 'chat':
      return route.conversationId ? `/chat/${encodeURIComponent(route.conversationId)}` : '/chat';
    case 'voice':
      return '/parler';
    case 'conversations':
      return '/conversations';
    case 'tasks':
      return '/tasks';
    case 'task':
      return `/tasks/${encodeURIComponent(route.id)}`;
    case 'approvals':
      return '/approvals';
    case 'settings':
      return '/settings';
  }
}

export function href(route: Route): string {
  return `#${routeToPath(route)}`;
}

export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  const target = href(route);
  if (options.replace) {
    window.history.replaceState(null, '', target);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else if (window.location.hash !== target) {
    window.location.hash = target;
  }
}

export function navigateToPath(path: string, options: { replace?: boolean } = {}): void {
  const target = path.startsWith('#') ? path : `#${path.startsWith('/') ? path : `/${path}`}`;
  if (options.replace) {
    window.history.replaceState(null, '', target);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
}

function getSnapshot(): string {
  return window.location.hash;
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, getSnapshot, () => '');
  return parseHash(hash);
}
