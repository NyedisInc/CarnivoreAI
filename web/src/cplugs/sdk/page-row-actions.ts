import { SvelteMap } from 'svelte/reactivity';

export interface PageRowActionPage {
  key: string;
  src: string | null;
  title: string;
}

export interface PageRowAction {
  plugin: string;
  id: string;
  label: () => string;
  enabled: () => boolean;
  targetOf: (page: PageRowActionPage) => string | null;
  run: (target: string) => void;
}

const actions = new SvelteMap<string, PageRowAction>();

export class PageRowActionConflict extends Error {}

export function registerPageRowAction(action: PageRowAction): void {
  const owner = [...actions.values()].find((held) => held.id === action.id && held.plugin !== action.plugin);
  if (owner) throw new PageRowActionConflict(`page row action "${action.id}" is already registered by plugin "${owner.plugin}"`);
  actions.set(`${action.plugin}:${action.id}`, action);
}

export function pageRowActions(): PageRowAction[] {
  return [...actions.values()].filter((action) => action.enabled());
}

export function resetPageRowActions(): void {
  actions.clear();
}
