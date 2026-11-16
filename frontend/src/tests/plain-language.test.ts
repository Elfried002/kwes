import { describe, expect, it } from 'vitest';
import {
  activitySentence,
  stepStateLabel,
  stepStateTone,
  taskStateLabel,
  taskStateTone,
  workSentence,
} from '../lib/plain-language';
import type { StepStatus, TaskStatus } from '../lib/types';

/** Aucun de ces mots ne doit apparaître dans l'espace connecté. */
const FORBIDDEN = ['worker', 'skill', 'sse', 'websocket', 'api', 'backend', 'orchestrateur', 'endpoint'];

const TASK_STATUSES: TaskStatus[] = [
  'queued',
  'planning',
  'running',
  'awaiting_approval',
  'paused',
  'completed',
  'failed',
  'cancelled',
];

const STEP_STATUSES: StepStatus[] = [
  'pending',
  'ready',
  'running',
  'awaiting_approval',
  'completed',
  'failed',
  'skipped',
];

describe('libellés humains', () => {
  it('couvre tous les états de travail sans jargon', () => {
    for (const status of TASK_STATUSES) {
      const label = taskStateLabel(status);
      expect(label.length).toBeGreaterThan(0);
      const lowered = label.toLowerCase();
      for (const word of FORBIDDEN) expect(lowered).not.toContain(word);
    }
  });

  it('couvre tous les états d’étape sans jargon', () => {
    for (const status of STEP_STATUSES) {
      const label = stepStateLabel(status);
      expect(label.length).toBeGreaterThan(0);
      const lowered = label.toLowerCase();
      for (const word of FORBIDDEN) expect(lowered).not.toContain(word);
    }
  });

  it('parle d’accord quand Kwes attend une décision', () => {
    expect(taskStateLabel('awaiting_approval').toLowerCase()).toContain('accord');
    expect(stepStateLabel('awaiting_approval').toLowerCase()).toContain('accord');
    expect(taskStateLabel('completed')).toBe('Terminé');
    expect(taskStateTone('awaiting_approval')).toBe('warning');
    expect(taskStateTone('completed')).toBe('success');
    expect(stepStateTone('failed')).toBe('danger');
  });
});

describe('phrases de suivi', () => {
  it('décrit le travail en cours avec son avancement', () => {
    const sentence = workSentence('running', 62);
    expect(sentence).toContain('62 %');
    expect(sentence.toLowerCase()).not.toContain('progression');
  });

  it('borne un avancement incohérent', () => {
    expect(workSentence('running', Number.NaN)).toContain('0 %');
    expect(workSentence('running', 180)).toContain('100 %');
  });

  it('traduit les nouvelles du serveur sans vocabulaire technique', () => {
    expect(activitySentence('task.awaiting_approval')).toContain('accord');
    expect(activitySentence('task.step.started')).toContain('étape');
    expect(activitySentence('task.created')).toContain('nouveau travail');

    const known = [
      'task.created',
      'task.updated',
      'task.step.started',
      'task.step.completed',
      'task.awaiting_approval',
      'task.failed',
      'conversation.completed',
      'notification.created',
      'system.status',
      'unknown.event',
    ];
    for (const event of known) {
      const sentence = activitySentence(event).toLowerCase();
      expect(sentence.endsWith('.') || sentence.endsWith('…')).toBe(true);
      for (const word of FORBIDDEN) expect(sentence).not.toContain(word);
    }
  });
});
