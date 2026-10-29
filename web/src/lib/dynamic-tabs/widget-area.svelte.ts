import { tabRegistry, type TabRegistry } from './registry';
import { WIDGET_AREA_STATES, type WidgetAreaState } from './types';

export const WIDGET_AREA_STORAGE_KEY = 'carnivore.session.sidebar.widgetArea';

export const FALLBACK_AREA_STATE: WidgetAreaState = 'full';

const RENAMED: Readonly<Record<string, WidgetAreaState>> = { open: 'full', mini: 'glance' };

export function snapAreaState(heightPx: number, glancePx: number, fullPx: number): WidgetAreaState {
  const anchors: [WidgetAreaState, number][] = [
    ['closed', 0],
    ['glance', glancePx],
    ['full', Math.max(fullPx, glancePx)],
  ];
  let best: [WidgetAreaState, number] = anchors[0]!;
  for (const anchor of anchors) if (Math.abs(heightPx - anchor[1]) <= Math.abs(heightPx - best[1])) best = anchor;
  return best[0];
}

export function stepAreaState(state: WidgetAreaState, by: 1 | -1): WidgetAreaState {
  const at = WIDGET_AREA_STATES.indexOf(state);
  return WIDGET_AREA_STATES[Math.min(WIDGET_AREA_STATES.length - 1, Math.max(0, at + by))]!;
}

type Store = Pick<Storage, 'getItem' | 'setItem'>;

function browserStorage(): Store | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function readAreaOverrides(storage: Store | null): Record<string, WidgetAreaState> {
  try {
    const raw = storage?.getItem(WIDGET_AREA_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, WidgetAreaState> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      const state = typeof value === 'string' ? (RENAMED[value] ?? value) : value;
      if ((WIDGET_AREA_STATES as readonly unknown[]).includes(state)) out[id] = state as WidgetAreaState;
    }
    return out;
  } catch (err) {
    console.warn('WidgetArea: stored states unreadable, using the defaults', err);
    return {};
  }
}

export class WidgetAreaStore {
  overrides = $state<Record<string, WidgetAreaState>>({});

  #registry: TabRegistry;
  #storage: () => Store | null;

  constructor(registry: TabRegistry, storage: () => Store | null = browserStorage) {
    this.#registry = registry;
    this.#storage = storage;
    this.overrides = readAreaOverrides(storage());
  }

  stateFor(tabId: string): WidgetAreaState {
    return this.overrides[tabId] ?? this.#registry.get(tabId)?.widgetArea ?? FALLBACK_AREA_STATE;
  }

  set(tabId: string, state: WidgetAreaState): void {
    if (this.overrides[tabId] === state) return;
    this.overrides = { ...this.overrides, [tabId]: state };
    try {
      this.#storage()?.setItem(WIDGET_AREA_STORAGE_KEY, JSON.stringify(this.overrides));
    } catch (err) {
      console.warn('WidgetArea: could not remember the state', err);
    }
  }

  toggle(tabId: string): WidgetAreaState {
    const next: WidgetAreaState = this.stateFor(tabId) === 'full' ? 'closed' : 'full';
    this.set(tabId, next);
    return next;
  }
}

export const widgetArea = new WidgetAreaStore(tabRegistry);
