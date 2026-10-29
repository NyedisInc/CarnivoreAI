import type { HuddleItem, TaskManagerState } from './huddle-model';

export const FORK_STATES: readonly TaskManagerState[] = ['open', 'waiting', 'todo', 'review', 'done'];

export interface ForkDraft {
  title: string;
  forkState: TaskManagerState;
  parentState: TaskManagerState | '';
}

export function forkDraft(item: Pick<HuddleItem, 'title'>): ForkDraft {
  return { title: item.title ?? '', forkState: 'open', parentState: '' };
}

export function forkBody(item: Pick<HuddleItem, 'title'>, draft: ForkDraft): Record<string, string> {
  const body: Record<string, string> = {};
  if (draft.title.trim() !== (item.title ?? '').trim()) body.title = draft.title.trim();
  if (draft.forkState !== 'open') body.fork_state = draft.forkState;
  if (draft.parentState !== '') body.parent_state = draft.parentState;
  return body;
}
