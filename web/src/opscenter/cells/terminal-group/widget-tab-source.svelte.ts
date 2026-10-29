import type { PlacementOptionValue, PlacementOptions } from '../../widgets/placement-options';
import type { PlacementSource } from '../../../lib/zone-shell/source';

export const WIDGET_TAB_OPTIONS_KEY = 'cloudecode.opscenter.widget-tab-options.v1';

function load(): Record<string, PlacementOptions> {
  try {
    const raw = globalThis.localStorage?.getItem(WIDGET_TAB_OPTIONS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, PlacementOptions>) : {};
  } catch {
    return {};
  }
}

let held = $state<Record<string, PlacementOptions>>(load());

function persist(): void {
  try {
    globalThis.localStorage?.setItem(WIDGET_TAB_OPTIONS_KEY, JSON.stringify(held));
  } catch {
  }
}

export function widgetTabOptions(tab: string): PlacementOptions | undefined {
  return held[tab];
}

export function moveWidgetTabOptions(from: string, to: string | null): void {
  if (!(from in held)) return;
  const { [from]: options, ...rest } = held;
  held = to && options ? { ...rest, [to]: options } : rest;
  persist();
}

export function createWidgetTabSource(actions: { remove: (tab: string) => void; swap: (tab: string, view: string) => void }): PlacementSource {
  return {
    setOption(key: string, option: string, value: PlacementOptionValue | null): void {
      const next: Record<string, PlacementOptionValue> = { ...held[key] };
      if (value === null) delete next[option];
      else next[option] = value;
      held = { ...held, [key]: next };
      persist();
    },
    setView(key: string, view: string): void {
      actions.swap(key, view);
    },
    resetOptions(key: string): void {
      moveWidgetTabOptions(key, null);
    },
    remove(key: string): boolean {
      actions.remove(key);
      return true;
    },
  };
}
