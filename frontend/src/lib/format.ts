import type { StepStatus, TaskStatus } from './types';

export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fr-FR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('fr-FR', { timeStyle: 'short' }).format(date);
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  const diff = date.getTime() - Date.now();
  const abs = Math.abs(diff);
  const formatter = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' });
  if (abs < 60_000) return formatter.format(Math.round(diff / 1000), 'second');
  if (abs < 3_600_000) return formatter.format(Math.round(diff / 60_000), 'minute');
  if (abs < 86_400_000) return formatter.format(Math.round(diff / 3_600_000), 'hour');
  if (abs < 2_592_000_000) return formatter.format(Math.round(diff / 86_400_000), 'day');
  return formatDateTime(iso);
}

export function formatCountdown(iso: string | null | undefined): string {
  if (!iso) return 'sans échéance';
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return 'sans échéance';
  const diff = target - Date.now();
  if (diff <= 0) return 'expirée';
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `expire dans ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `expire dans ${hours} h`;
  return `expire dans ${Math.floor(hours / 24)} j`;
}

export function taskTone(status: TaskStatus): Tone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'danger';
    case 'awaiting_approval':
      return 'warning';
    case 'running':
    case 'planning':
      return 'accent';
    default:
      return 'neutral';
  }
}

export function stepTone(status: StepStatus): Tone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'danger';
    case 'awaiting_approval':
      return 'warning';
    case 'running':
      return 'accent';
    default:
      return 'neutral';
  }
}

export function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function initials(email: string): string {
  if (!email) return 'K';
  return email.slice(0, 2).toUpperCase();
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 6) return 'Bonne nuit';
  if (hour < 12) return 'Bonjour';
  if (hour < 18) return 'Bon après-midi';
  return 'Bonsoir';
}

export function truncate(value: string, max = 90): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

export function conversationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    active: 'Active',
    archived: 'Archivée',
    deleted: 'Supprimée',
    closed: 'Fermée',
  };
  return labels[status] ?? status;
}
