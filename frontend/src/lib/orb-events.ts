import type { TaskEventData, WsEnvelope } from './types';
import type { OrbEventType } from '../components/orb/orb-state-machine';

export interface OrbMachineAction {
  type: OrbEventType;
  taskId?: string;
  detail?: string;
}

/**
 * Traduction pure des événements serveur → événements de la machine à états.
 * Table de référence : CONTRACTS.md § « Mapping événements → états de l'Orb ».
 * Aucune inspection du contenu de texte : seuls les champs structurels comptent.
 */
export function orbEventFromEnvelope(envelope: WsEnvelope): OrbMachineAction | null {
  const data = (envelope.data ?? {}) as TaskEventData;
  const taskId = typeof data.task_id === 'string' ? data.task_id : undefined;

  switch (envelope.event) {
    case 'task.updated': {
      switch (data.status) {
        case 'running':
          return { type: 'TASK_RUNNING', taskId };
        case 'awaiting_approval':
          return { type: 'TASK_AWAITING_APPROVAL', taskId };
        case 'completed':
          return { type: 'TASK_COMPLETED', taskId, detail: 'Mission terminée (confirmée par le serveur).' };
        case 'failed':
          return { type: 'TASK_FAILED', taskId, detail: 'Mission échouée.' };
        case 'paused':
        case 'cancelled':
          return { type: 'RESET', taskId };
        default:
          return null;
      }
    }
    case 'task.step.started':
      return {
        type: 'TASK_STEP_STARTED',
        taskId,
        detail: typeof data.title === 'string' ? data.title : undefined,
      };
    case 'task.awaiting_approval':
      return { type: 'TASK_AWAITING_APPROVAL', taskId };
    case 'task.failed':
      return {
        type: 'TASK_FAILED',
        taskId,
        detail: typeof data.error_code === 'string' ? data.error_code : undefined,
      };
    default:
      return null;
  }
}
