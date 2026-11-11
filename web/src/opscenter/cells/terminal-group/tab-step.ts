import { inputFocus } from '../../lib/input-focus.svelte';
import { PRIMARY_SLOT } from '../../engine/model';

export interface StepGroup {
  tabs(): string[];
  active(): string;
  select(tab: string): void;
}

const groups = new Map<string, StepGroup>();

export function registerTabGroup(instance: string, group: StepGroup): () => void {
  groups.set(instance, group);
  return () => {
    if (groups.get(instance) === group) groups.delete(instance);
  };
}

export function stepActiveTabs(dir: -1 | 1): boolean {
  const all = [...groups.values()];
  const held = (id: string | null | undefined): StepGroup | undefined => (id ? all.find((g) => g.tabs().includes(id)) : undefined);
  const focused = (): string | undefined =>
    document.activeElement?.closest('.oc-tg')?.querySelector<HTMLElement>('[data-tab]')?.dataset.tab;
  const group = held(inputFocus.owner) ?? held(inputFocus.selected) ?? held(focused()) ?? groups.get(PRIMARY_SLOT);
  if (!group) return true;
  const tabs = group.tabs();
  if (tabs.length < 2) return true;
  const at = tabs.indexOf(group.active());
  group.select(tabs[(at + dir + tabs.length) % tabs.length]);
  return true;
}
