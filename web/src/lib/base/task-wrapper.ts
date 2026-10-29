
export const TASK_STATES = ['compact', 'opened', 'detailed'] as const;

export type TaskState = (typeof TASK_STATES)[number];

export type TaskPart = 'tabs';

const PARTS: Readonly<Record<TaskState, readonly TaskPart[]>> = Object.freeze({
  compact: [],
  opened: ['tabs'],
  detailed: ['tabs'],
});

export function isTaskState(value: unknown): value is TaskState {
  return (TASK_STATES as readonly unknown[]).includes(value);
}

const LEGACY: Readonly<Record<string, TaskState>> = Object.freeze({ normal: 'opened', expanded: 'detailed' });

export function legacyTaskState(value: unknown): TaskState | null {
  if (isTaskState(value)) return value;
  return typeof value === 'string' ? LEGACY[value] ?? null : null;
}

export function nextTaskState(state: TaskState): TaskState {
  return TASK_STATES[(TASK_STATES.indexOf(state) + 1) % TASK_STATES.length] as TaskState;
}

export function partsOf(state: TaskState): readonly TaskPart[] {
  return PARTS[state];
}
