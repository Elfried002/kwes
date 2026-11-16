import { describe, expect, it } from 'vitest';
import {
  ORB_EVENTS,
  ORB_STATES,
  ORB_STATE_META,
  TRANSITIONS,
  canTransition,
  isOrbState,
  reduce,
  transition,
  type OrbEvent,
  type OrbEventType,
  type OrbState,
} from '../components/orb/orb-state-machine';

describe('machine à états de l’Orb — mapping du contrat', () => {
  it('idle est l’état neutre et ne change pas sans événement', () => {
    expect(transition('idle', 'RESET')).toMatchObject({ state: 'idle', changed: false });
  });

  it('micro actif → listening, micro coupé → idle', () => {
    expect(transition('idle', 'MIC_START').state).toBe('listening');
    expect(transition('listening', 'MIC_STOP').state).toBe('idle');
  });

  it('POST /chat en vol → thinking', () => {
    expect(transition('idle', 'CHAT_SUBMITTED').state).toBe('thinking');
    expect(transition('response', 'CHAT_SUBMITTED').state).toBe('thinking');
  });

  it('task.updated running et task.step.started → executing', () => {
    expect(transition('thinking', 'TASK_RUNNING').state).toBe('executing');
    expect(transition('thinking', 'TASK_STEP_STARTED').state).toBe('executing');
    expect(transition('executing', 'TASK_STEP_STARTED').state).toBe('executing');
  });

  it('task.awaiting_approval → waiting_approval', () => {
    expect(transition('executing', 'TASK_AWAITING_APPROVAL').state).toBe('waiting_approval');
    expect(transition('idle', 'TASK_AWAITING_APPROVAL').state).toBe('waiting_approval');
    expect(transition('waiting_approval', 'APPROVAL_DECIDED').state).toBe('thinking');
  });

  it('réponse assistant affichée → response', () => {
    expect(transition('thinking', 'CHAT_RESPONSE').state).toBe('response');
    expect(transition('idle', 'CHAT_RESPONSE').state).toBe('response');
  });

  it('task completed → success, puis idle après 2 s (TIMEOUT)', () => {
    const done = transition('executing', 'TASK_COMPLETED');
    expect(done.state).toBe('success');
    const afterDelay = transition(done.state, 'TIMEOUT');
    expect(afterDelay.state).toBe('idle');
  });

  it('task.failed et erreur API → error', () => {
    expect(transition('executing', 'TASK_FAILED').state).toBe('error');
    expect(transition('thinking', 'API_ERROR').state).toBe('error');
    expect(transition('idle', 'API_ERROR').state).toBe('error');
  });

  it('audio en lecture → speaking', () => {
    expect(transition('response', 'AUDIO_START').state).toBe('speaking');
  });
});

describe('transitions invalides', () => {
  const invalid: Array<[OrbState, OrbEventType]> = [
    ['idle', 'MIC_STOP'],
    ['idle', 'TIMEOUT'],
    ['idle', 'AUDIO_END'],
    ['thinking', 'MIC_START'],
    ['thinking', 'MIC_STOP'],
    ['executing', 'MIC_START'],
    ['executing', 'CHAT_RESPONSE'],
    ['waiting_approval', 'TASK_STEP_STARTED'],
    ['waiting_approval', 'MIC_START'],
    ['error', 'AUDIO_END'],
    ['error', 'TIMEOUT'],
    ['success', 'TASK_COMPLETED'],
    ['speaking', 'CHAT_SUBMITTED'],
  ];

  it.each(invalid)('%s + %s est un no-op', (state, event) => {
    const result = transition(state, event);
    expect(result.state).toBe(state);
    expect(result.changed).toBe(false);
    expect(canTransition(state, event)).toBe(false);
  });

  it('error ne se réinitialise pas tout seul', () => {
    expect(transition('error', 'TIMEOUT').state).toBe('error');
    expect(transition('error', 'RESET').state).toBe('idle');
    expect(transition('error', 'CHAT_SUBMITTED').state).toBe('thinking');
  });
});

describe('sortie de l’état speaking', () => {
  it('restaure l’état d’origine fourni par l’appelant', () => {
    const entered = transition('executing', 'AUDIO_START');
    expect(entered).toMatchObject({ state: 'speaking', resumeFrom: 'executing', changed: true });
    expect(transition('speaking', 'AUDIO_END', entered.resumeFrom).state).toBe('executing');
  });

  it('retombe sur response par défaut', () => {
    expect(transition('speaking', 'AUDIO_END').state).toBe('response');
    expect(transition('speaking', 'AUDIO_END', 'speaking').state).toBe('response');
  });

  it('une nouvelle entrée en speaking n’écrase pas l’origine', () => {
    const entered = transition('response', 'AUDIO_START');
    expect(entered.resumeFrom).toBe('response');
    expect(transition(entered.state, 'TASK_RUNNING').state).toBe('executing');
  });
});

describe('déterminisme et intégrité de la table', () => {
  it('produit toujours le même résultat pour une même entrée', () => {
    for (const state of ORB_STATES) {
      for (const event of ORB_EVENTS) {
        const first = transition(state, event);
        const second = transition(state, event);
        expect(second).toEqual(first);
      }
    }
  });

  it('toute cible déclarée est un état valide', () => {
    for (const state of ORB_STATES) {
      const row = TRANSITIONS[state];
      for (const [event, target] of Object.entries(row)) {
        expect(ORB_EVENTS).toContain(event as OrbEventType);
        expect(isOrbState(target)).toBe(true);
      }
    }
  });

  it('canTransition est cohérent avec transition', () => {
    for (const state of ORB_STATES) {
      for (const event of ORB_EVENTS) {
        const allowed = canTransition(state, event);
        const result = transition(state, event);
        if (!allowed) {
          expect(result.state).toBe(state);
        } else {
          expect(isOrbState(result.state)).toBe(true);
        }
      }
    }
  });

  it('une suite complète de mission revient à idle', () => {
    const events: OrbEvent[] = [
      { type: 'CHAT_SUBMITTED' },
      { type: 'TASK_RUNNING', taskId: 't1' },
      { type: 'TASK_STEP_STARTED', taskId: 't1' },
      { type: 'TASK_AWAITING_APPROVAL', taskId: 't1' },
      { type: 'APPROVAL_DECIDED', taskId: 't1' },
      { type: 'TASK_RUNNING', taskId: 't1' },
      { type: 'TASK_COMPLETED', taskId: 't1' },
      { type: 'TIMEOUT' },
    ];
    expect(reduce('idle', events)).toBe('idle');
  });

  it('reduce est séquentiel et respecte les no-op', () => {
    const events: OrbEvent[] = [
      { type: 'MIC_START' },
      { type: 'CHAT_SUBMITTED' },
      { type: 'CHAT_RESPONSE' },
      { type: 'AUDIO_START' },
      { type: 'AUDIO_END' },
    ];
    expect(reduce('idle', events)).toBe('response');
  });
});

describe('métadonnées accessibles', () => {
  it('chaque état possède un libellé et une annonce non vides', () => {
    for (const state of ORB_STATES) {
      expect(ORB_STATE_META[state].label.length).toBeGreaterThan(0);
      expect(ORB_STATE_META[state].announcement.length).toBeGreaterThan(0);
      expect(ORB_STATE_META[state].caption.length).toBeGreaterThan(0);
    }
  });

  it('seul speaking représente une lecture audio et seul executing un écran', () => {
    for (const state of ORB_STATES) {
      expect(ORB_STATE_META[state].audio).toBe(state === 'speaking');
      expect(ORB_STATE_META[state].device).toBe(state === 'executing');
    }
  });

  it('les libellés du design system sont respectés', () => {
    expect(ORB_STATE_META.idle.label).toBe('Prêt');
    expect(ORB_STATE_META.listening.label).toBe('Écoute');
    expect(ORB_STATE_META.thinking.label).toBe('Réflexion');
    expect(ORB_STATE_META.executing.label).toBe('Exécution');
    expect(ORB_STATE_META.speaking.label).toBe('Parle');
    expect(ORB_STATE_META.error.label).toBe('Incident');
  });
});
