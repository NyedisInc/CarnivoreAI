import { cplugPopoutTabs, cplugPopoutTabsOn } from '../../plugins/host/readers';
import { runtimePopoutTabDefs } from '../cplug-ui/plugin-tabs.svelte';
import type { DynamicTabDef } from './types';

export const POPOUT_TABS: readonly DynamicTabDef[] = [...cplugPopoutTabs()];

export function popoutTabsOn(): DynamicTabDef[] {
  const runtime = runtimePopoutTabDefs();
  if (runtime.length === 0) return [...POPOUT_TABS];
  const seen = new Set(POPOUT_TABS.map((def) => def.id));
  return [...POPOUT_TABS, ...runtime.filter((def) => !seen.has(def.id))];
}

export function popoutTab(id: string): DynamicTabDef | null {
  return popoutTabsOn().find((def) => def.id === id && def.popout === true) ?? null;
}

export function popoutTabOn(id: string): DynamicTabDef | null {
  const compiled = cplugPopoutTabsOn();
  const seen = new Set(compiled.map((def) => def.id));
  const tabs = [...compiled, ...runtimePopoutTabDefs().filter((def) => !seen.has(def.id))];
  return tabs.find((def) => def.id === id && def.popout === true) ?? null;
}
