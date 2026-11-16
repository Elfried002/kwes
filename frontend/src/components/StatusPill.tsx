import type { ReactNode } from 'react';
import type { StepStatus, TaskStatus } from '../lib/types';
import { stepStateLabel, stepStateTone, taskStateLabel, taskStateTone } from '../lib/plain-language';

export function StatusPill({ status }: { status: TaskStatus }) {
  return <span className={`badge badge--${taskStateTone(status)}`}>{taskStateLabel(status)}</span>;
}

export function StepPill({ status }: { status: StepStatus }) {
  return <span className={`badge badge--${stepStateTone(status)}`}>{stepStateLabel(status)}</span>;
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
