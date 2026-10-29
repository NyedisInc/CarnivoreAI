import { untrack } from 'svelte';
import type { SlotId } from '../../engine/types';

export interface DeclaredAction {
  id: string;
  label: string;
  checked?: boolean;
  toggle?: boolean;
  blocked?: string;
  group?: string;
  run: () => void;
}

const declared = new Map<string, Map<string, readonly DeclaredAction[]>>();
const version = $state({ n: 0 });

export function declareWidgetActions(slot: SlotId | string, source: string, actions: readonly DeclaredAction[]): () => void {
  const held = declared.get(slot) ?? new Map<string, readonly DeclaredAction[]>();
  held.set(source, actions);
  declared.set(slot, held);
  bump();
  return () => {
    const now = declared.get(slot);
    if (!now || now.get(source) !== actions) return;
    now.delete(source);
    if (!now.size) declared.delete(slot);
    bump();
  };
}

function bump(): void {
  untrack(() => {
    version.n += 1;
  });
}

export function declaredActionsFor(slot: SlotId | string): DeclaredAction[] {
  void version.n;
  return [...(declared.get(slot)?.values() ?? [])].flat();
}
