import { readKey, writeKey } from '../drawer/storage';
import { drawerEnv } from '../drawer/env';

export const STORAGE_KEY = 'carnivore.menu.order';
export const PREFERENCE_FIELD = 'menu_order';

interface BridgeGlobals {
  PreferenceBridge?: {
    read?(field: string, fallback: () => unknown): unknown;
    write?(field: string, value: string[], local: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
  };
}

const view = $state<{ ids: string[] }>({ ids: [] });

function clean(value: unknown): string[] {
  return Array.isArray(value) ? [...new Set(value.filter((v): v is string => typeof v === 'string' && v !== ''))] : [];
}

export function resolveMenuOrder<T extends { id: string }>(items: readonly T[], stored: readonly string[] = []): T[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const picked = stored.filter((id) => byId.has(id)).map((id) => byId.get(id) as T);
  const seen = new Set(picked.map((item) => item.id));
  return [...picked, ...items.filter((item) => !seen.has(item.id))];
}

export function moveBefore(order: readonly string[], id: string, beforeId: string | null): string[] {
  const rest = order.filter((x) => x !== id);
  const at = beforeId === null ? rest.length : rest.indexOf(beforeId);
  if (at === -1 || beforeId === id) return [...order];
  return [...rest.slice(0, at), id, ...rest.slice(at)];
}

export function orderedMenuItems<T extends { id: string }>(items: readonly T[]): T[] {
  return resolveMenuOrder(items, view.ids);
}

export function saveMenuOrder(ids: readonly string[]): void {
  const next = clean(ids);
  view.ids = next;
  const writeLocal = (): void => {
    try {
      writeKey(STORAGE_KEY, JSON.stringify(next));
    } catch (err) {
      console.warn('MenuOrder: could not persist the menu order:', err);
    }
  };
  const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
  if (bridge && typeof bridge.write === 'function') {
    bridge.write(PREFERENCE_FIELD, next, writeLocal).catch((err: unknown) => {
      console.warn('MenuOrder: could not share the menu order:', err);
    });
  } else {
    writeLocal();
  }
}

function loadLocal(): string[] {
  try {
    return clean(JSON.parse(readKey(STORAGE_KEY) || '[]'));
  } catch {
    return [];
  }
}

export function startMenuOrder(): () => void {
  const bridge = (drawerEnv() as BridgeGlobals).PreferenceBridge;
  view.ids = clean(bridge && typeof bridge.read === 'function' ? bridge.read(PREFERENCE_FIELD, loadLocal) : loadLocal());
  return bridge && typeof bridge.follow === 'function'
    ? bridge.follow(PREFERENCE_FIELD, (value) => { view.ids = clean(value); })
    : () => {};
}
