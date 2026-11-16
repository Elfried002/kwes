import type { ReactNode } from 'react';

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

export type IconName =
  | 'home'
  | 'chat'
  | 'history'
  | 'activity'
  | 'shield'
  | 'settings'
  | 'mic'
  | 'mic-off'
  | 'send'
  | 'stop'
  | 'copy'
  | 'pause'
  | 'play'
  | 'cancel'
  | 'plus'
  | 'refresh'
  | 'trash'
  | 'back'
  | 'logout'
  | 'spark'
  | 'check'
  | 'alert'
  | 'clock'
  | 'external'
  | 'install'
  | 'share';

const PATHS: Record<IconName, ReactNode> = {
  home: <path d="M3.5 10.5 12 3.5l8.5 7v9a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z" />,
  chat: (
    <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H9l-5 4z" />
  ),
  history: (
    <>
      <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3.5 4v4.5H8" />
      <path d="M12 8v4.5l3 1.8" />
    </>
  ),
  activity: (
    <>
      <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3.2 19.5 6v5.2c0 4.3-3.1 7.9-7.5 9.6-4.4-1.7-7.5-5.3-7.5-9.6V6z" />
      <path d="m9 12 2.2 2.2L15.5 10" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6" />
    </>
  ),
  'mic-off': (
    <>
      <path d="M9 9v2a3 3 0 0 0 4.6 2.6M15 11V6a3 3 0 0 0-5.6-1.5" />
      <path d="M5.5 11a6.5 6.5 0 0 0 10 5.5M12 17.5V21M9 21h6" />
      <path d="m3 3 18 18" />
    </>
  ),
  send: <path d="M4 11.8 20 4l-6.6 16-2.7-6.1z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M15 5.5A2.5 2.5 0 0 0 12.5 3h-7A2.5 2.5 0 0 0 3 5.5v7A2.5 2.5 0 0 0 5.5 15" />
    </>
  ),
  pause: (
    <>
      <rect x="7" y="5" width="3.6" height="14" rx="1" />
      <rect x="13.4" y="5" width="3.6" height="14" rx="1" />
    </>
  ),
  play: <path d="M8 5.5v13l11-6.5z" />,
  cancel: <path d="M6 6l12 12M18 6 6 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: (
    <>
      <path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1" />
      <path d="M20.5 4v4.5H16" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16M9 7V4.8A1.8 1.8 0 0 1 10.8 3h2.4A1.8 1.8 0 0 1 15 4.8V7" />
      <path d="M6.5 7 7.4 20a1 1 0 0 0 1 .9h7.2a1 1 0 0 0 1-.9L17.5 7" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  back: <path d="M15 5 8 12l7 7" />,
  logout: (
    <>
      <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
      <path d="M15 8l4 4-4 4M19 12H9" />
    </>
  ),
  spark: <path d="M12 3l1.9 5.4L19.5 10l-5.6 1.6L12 17l-1.9-5.4L4.5 10l5.6-1.6z" />,
  check: <path d="m5 12.5 4.5 4.5L19 7" />,
  alert: (
    <>
      <path d="M12 4 21 20H3z" />
      <path d="M12 10v4.5M12 17.3v.2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
  external: <path d="M13 4h7v7M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />,
  install: (
    <>
      <path d="M12 3v11" />
      <path d="m7.5 9.5 4.5 4.5 4.5-4.5" />
      <path d="M4.5 20.5h15" />
    </>
  ),
  share: (
    <>
      <path d="M12 15V3.5" />
      <path d="m8 7 4-3.5L16 7" />
      <path d="M6.5 11.5H4.5v8h15v-8h-2" />
    </>
  ),
};

export function Icon({ name, size = 20, className }: IconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
