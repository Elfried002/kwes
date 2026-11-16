import type { ReactNode } from 'react';
import { STEP_STATUS_LABELS, TASK_STATUS_LABELS, type StepStatus, type TaskStatus } from '../lib/types';
import { stepTone, taskTone } from '../lib/format';

export function StatusPill({ status }: { status: TaskStatus }) {
  return <span className={`badge badge--${taskTone(status)}`}>{TASK_STATUS_LABELS[status] ?? status}</span>;
}

export function StepPill({ status }: { status: StepStatus }) {
  return <span className={`badge badge--${stepTone(status)}`}>{STEP_STATUS_LABELS[status] ?? status}</span>;
}

export function ToneBadge({
  tone,
  children,
}: {
  tone: 'neutral' | 'accent' | 'success' | 'warning' | 'danger';
  children: ReactNode;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
