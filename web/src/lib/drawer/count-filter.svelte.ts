/* and writes nothing */
import { drawerController } from './controller-ref';
import type { CountKind } from './agent-counts';

const state = $state<{ kind: CountKind | null }>({ kind: null });

export function activeCountFilter(): CountKind | null {
  return state.kind;
}

export function setCountFilter(kind: CountKind | null): void {
  if (state.kind === kind) return;
  state.kind = kind;
  drawerController()?.repaint();
}

export function toggleCountFilter(kind: CountKind): void {
  setCountFilter(state.kind === kind ? null : kind);
}
