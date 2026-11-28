import { authFetch, familyOf, resourcePush } from '../sdk';
import { TASK_MANAGER_LIST_FAMILY, followTaskManagerDelta } from '../sdk/task-manager-delta';
import { parseSteps, stepsMoved, type ClaimKey, type ListSteps, type StepsEntry } from './task-manager-steps';

export const STEPS_TOPIC = 'session_tasks:huddle';

export const taskManagerSteps = $state<{ byList: Record<string, ListSteps> }>({ byList: {} });

export function stepsOfItem(list: string, id: number): StepsEntry | null {
  return taskManagerSteps.byList[list]?.items[String(id)] ?? null;
}

export async function refreshSteps(): Promise<void> {
  try {
    taskManagerSteps.byList = parseSteps(await authFetch('/cplugs/huddle/steps'));
  } catch (error) {
    console.warn('huddle: could not read session steps', error);
  }
}

let holders = 0;
let stop: (() => void) | null = null;
const claims = new Map<number, ClaimKey>();

let missed = false;

function tabHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

function readUnlessHidden(): void {
  if (tabHidden()) {
    missed = true;
    return;
  }
  missed = false;
  void refreshSteps();
}

function onVisibility(): void {
  if (!tabHidden() && missed) readUnlessHidden();
}

export function holdSteps(): void {
  holders += 1;
  if (stop) return;
  const stopSteps = resourcePush().onChange((topics) => {
    if (topics.includes(STEPS_TOPIC)) readUnlessHidden();
  });
  const stopDelta = followTaskManagerDelta({
    touches: (delta) => stepsMoved(taskManagerSteps.byList, delta, claims),
    fallback: (topic) => familyOf(topic) === TASK_MANAGER_LIST_FAMILY,
    refresh: () => readUnlessHidden(),
    reconnect: true,
  });
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility);
  stop = () => {
    stopSteps();
    stopDelta();
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
  };
  readUnlessHidden();
}

export function releaseSteps(): void {
  holders = Math.max(0, holders - 1);
  if (holders > 0 || !stop) return;
  stop();
  stop = null;
  claims.clear();
  missed = false;
  taskManagerSteps.byList = {};
}
