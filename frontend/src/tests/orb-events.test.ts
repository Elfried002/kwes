import { describe, expect, it } from 'vitest';
import { orbEventFromEnvelope } from '../lib/orb-events';
import type { WsEnvelope } from '../lib/types';

function envelope(event: string, data: Record<string, unknown>): WsEnvelope {
  return { event, event_id: 'e1', timestamp: '2026-11-16T10:00:00Z', data };
}

describe('mapping WebSocket → machine à états', () => {
  it('task.updated running → TASK_RUNNING', () => {
    const action = orbEventFromEnvelope(envelope('task.updated', { task_id: 't1', status: 'running', progress: 10 }));
    expect(action).toEqual({ type: 'TASK_RUNNING', taskId: 't1' });
  });

  it('task.updated completed → TASK_COMPLETED', () => {
    const action = orbEventFromEnvelope(envelope('task.updated', { task_id: 't1', status: 'completed' }));
    expect(action?.type).toBe('TASK_COMPLETED');
    expect(action?.taskId).toBe('t1');
  });

  it('task.updated failed → TASK_FAILED', () => {
    expect(orbEventFromEnvelope(envelope('task.updated', { task_id: 't1', status: 'failed' }))?.type).toBe(
      'TASK_FAILED',
    );
  });

  it('task.updated awaiting_approval → TASK_AWAITING_APPROVAL', () => {
    expect(
      orbEventFromEnvelope(envelope('task.updated', { task_id: 't1', status: 'awaiting_approval' }))?.type,
    ).toBe('TASK_AWAITING_APPROVAL');
  });

  it('task.step.started → TASK_STEP_STARTED', () => {
    const action = orbEventFromEnvelope(envelope('task.step.started', { task_id: 't2', title: 'Recherche' }));
    expect(action).toEqual({ type: 'TASK_STEP_STARTED', taskId: 't2', detail: 'Recherche' });
  });

  it('task.awaiting_approval et task.failed sont mappés', () => {
    expect(orbEventFromEnvelope(envelope('task.awaiting_approval', { task_id: 't3' }))?.type).toBe(
      'TASK_AWAITING_APPROVAL',
    );
    expect(orbEventFromEnvelope(envelope('task.failed', { task_id: 't3', error_code: 'PROVIDER_UNAVAILABLE' }))).toEqual({
      type: 'TASK_FAILED',
      taskId: 't3',
      detail: 'PROVIDER_UNAVAILABLE',
    });
  });

  it('les événements de conversation ne pilotent jamais l’Orb directement', () => {
    expect(
      orbEventFromEnvelope(
        envelope('conversation.delta', { conversation_id: 'c1', delta: 'Kwes est en train de réfléchir' }),
      ),
    ).toBeNull();
    expect(
      orbEventFromEnvelope(envelope('conversation.completed', { conversation_id: 'c1', content: 'Mission terminée' })),
    ).toBeNull();
  });

  it('le texte du message n’influence jamais le mapping', () => {
    const withoutText = orbEventFromEnvelope(envelope('task.updated', { task_id: 't4', status: 'running' }));
    const withMisleadingText = orbEventFromEnvelope(
      envelope('task.updated', {
        task_id: 't4',
        status: 'running',
        content: 'Je suis terminé, success, error, awaiting_approval',
        title: 'completed',
      }),
    );
    expect(withMisleadingText).toEqual(withoutText);
  });

  it('un statut inconnu ou absent ne produit aucune transition', () => {
    expect(orbEventFromEnvelope(envelope('task.updated', { task_id: 't1' }))).toBeNull();
    expect(orbEventFromEnvelope(envelope('system.status', { status: 'ok' }))).toBeNull();
  });
});
