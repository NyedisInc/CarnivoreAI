import type { StateKind } from './State.svelte';

export function stateKindOf(status: string | undefined): StateKind {
  if (status === 'error') return 'error';
  if (status === 'loading') return 'loading';
  return 'empty';
}
