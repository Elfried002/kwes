import type { StepStatus, TaskStatus } from './types';

/**
 * Traductions de l'état interne vers des phrases humaines.
 *
 * Règle : ces libellés sont affichés dans l'espace connecté. Aucun terme
 * d'implémentation (worker, skill, SSE, API, orchestrateur) ne doit y figurer.
 */

export type TaskTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export function taskStateLabel(status: TaskStatus): string {
  switch (status) {
    case 'queued':
      return 'Il s’y met';
    case 'planning':
      return 'Il réfléchit';
    case 'running':
      return 'Kwes travaille dessus';
    case 'awaiting_approval':
      return 'Il attend votre accord';
    case 'paused':
      return 'En pause';
    case 'completed':
      return 'Terminé';
    case 'failed':
      return 'N’a pas abouti';
    case 'cancelled':
      return 'Arrêté';
  }
}

export function stepStateLabel(status: StepStatus): string {
  switch (status) {
    case 'pending':
      return 'Pas encore commencé';
    case 'ready':
      return 'Prêt à démarrer';
    case 'running':
      return 'En cours';
    case 'awaiting_approval':
      return 'Votre accord attendu';
    case 'completed':
      return 'Terminé';
    case 'failed':
      return 'N’a pas abouti';
    case 'skipped':
      return 'Passé';
  }
}

export function taskStateTone(status: TaskStatus): TaskTone {
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

export function stepStateTone(status: StepStatus): TaskTone {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'danger';
    case 'awaiting_approval':
      return 'warning';
    case 'running':
    case 'ready':
      return 'accent';
    default:
      return 'neutral';
  }
}

/** Phrase courte affichée sous un travail en cours, sans vocabulaire interne. */
export function workSentence(status: TaskStatus, progress: number): string {
  const percent = Number.isFinite(progress) ? Math.max(0, Math.min(100, Math.round(progress))) : 0;
  switch (status) {
    case 'queued':
      return 'Il va s’en occuper.';
    case 'planning':
      return 'Il réfléchit à la meilleure façon de s’y prendre.';
    case 'running':
      return `Il travaille dessus — ${percent} % du travail est fait.`;
    case 'awaiting_approval':
      return 'Il a besoin de votre accord pour continuer.';
    case 'paused':
      return 'Il est en pause. Vous pouvez reprendre quand vous voulez.';
    case 'completed':
      return 'C’est terminé. Le résultat est prêt.';
    case 'failed':
      return 'Ça n’a pas abouti. Vous pouvez relancer la demande.';
    case 'cancelled':
      return 'Vous avez arrêté ce travail.';
  }
}

/** Dernières nouvelles : événement technique → phrase lisible. */
export function activitySentence(event: string, data: Record<string, unknown> = {}): string {
  switch (event) {
    case 'task.created':
      return 'Kwes a commencé un nouveau travail.';
    case 'task.updated':
      return 'Il a avancé.';
    case 'task.step.started':
      return 'Il a commencé une étape.';
    case 'task.step.completed':
      return 'Il a terminé une étape.';
    case 'task.awaiting_approval':
      return 'Il a besoin de votre accord pour continuer.';
    case 'task.failed':
      return 'Une étape n’a pas abouti.';
    case 'conversation.delta':
      return 'Il écrit sa réponse…';
    case 'conversation.completed':
      return 'Sa réponse est prête.';
    case 'notification.created':
      return 'Quelque chose de nouveau est arrivé.';
    case 'system.status':
      return 'L’état du service a changé.';
    default:
      if (typeof data.status === 'string') return 'Il a avancé.';
      return 'Point d’avancement.';
  }
}
