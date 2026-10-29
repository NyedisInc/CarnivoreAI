import { isTaskState, type TaskState } from '../../../lib/base/task-wrapper';
import type { ViewChip } from '../../../cplugs/huddle/task-manager-view-filter.svelte';

export const MK2_DEFAULT_STATE: TaskState = 'compact';

const OPENING_CHIPS: readonly ViewChip[] = ['unread', 'needs_you'];

export const isMk2State = (value: unknown): value is TaskState => isTaskState(value);

export function effectiveState(state: TaskState, chip: ViewChip | null | undefined): TaskState {
  return state === 'compact' && chip && OPENING_CHIPS.includes(chip) ? 'opened' : state;
}
