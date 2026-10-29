import { getContext, setContext } from 'svelte';
import { huddle } from './huddle.svelte';

const VIEW = Symbol('task-manager-view');

export function pinView(key: string): void {
  setContext(VIEW, key);
}

export function viewKey(): () => string {
  const pinned = getContext<string | undefined>(VIEW);
  return () => pinned ?? huddle.selected;
}
