import { ALL_FILTERS_ON } from './model';
import type { FilterKey, Filters } from './types';

const KEY = 'oc.timeline.filters';

function load(): Filters {
  try {
    const stored = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? 'null') as Partial<Filters> | null;
    return { ...ALL_FILTERS_ON, ...Object.fromEntries(Object.entries(stored ?? {}).filter(([, v]) => typeof v === 'boolean')) };
  } catch {
    return { ...ALL_FILTERS_ON };
  }
}

class TimelineFilters {
  value = $state<Filters>(load());

  toggle(key: FilterKey): void {
    this.value = { ...this.value, [key]: !this.value[key] };
    try {
      globalThis.localStorage?.setItem(KEY, JSON.stringify(this.value));
    } catch {
    }
  }
}

export const timelineFilters = new TimelineFilters();
