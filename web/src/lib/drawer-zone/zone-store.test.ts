/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { DrawerZoneStore } from './zone-store.svelte';
import { ZONE_FIELD } from './zone-model';

interface FakeBridge {
  value: unknown;
  writes: unknown[];
  listeners: ((value: unknown) => void)[];
  read: (field: string) => unknown;
  write: (field: string, value: unknown) => Promise<{ status: string }>;
  follow: (field: string, apply: (value: unknown) => void) => () => void;
}

function installBridge(initial: unknown): FakeBridge {
  const bridge: FakeBridge = {
    value: initial,
    writes: [],
    listeners: [],
    read: () => bridge.value,
    write: async (field, value) => {
      expect(field).toBe(ZONE_FIELD);
      bridge.writes.push(value);
      bridge.value = value;
      return { status: 'committed' };
    },
    follow: (_field, apply) => {
      bridge.listeners.push(apply);
      return () => {};
    },
  };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = bridge;
  return bridge;
}

const ids = (store: DrawerZoneStore): string[] => store.items.map((i) => i.widget);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
  vi.useRealTimers();
});

describe('DrawerZoneStore', () => {
  test('absent paints the providers default and writes nothing', () => {
    const bridge = installBridge(null);
    const store = new DrawerZoneStore();
    store.start(null);
    expect(ids(store)).toEqual(['core.ledger']);
    expect(bridge.writes).toEqual([]);
  });

  test('a stored list wins, including an emptied one', () => {
    installBridge({ v: 1, items: [{ widget: 'core.keep-awake' }] });
    const a = new DrawerZoneStore();
    a.start(null);
    expect(ids(a)).toEqual(['core.keep-awake']);
    installBridge({ v: 1, items: [] });
    const b = new DrawerZoneStore();
    b.start(null);
    expect(ids(b)).toEqual([]);
  });

  test('add, reorder, look and remove each save the whole list', () => {
    const bridge = installBridge(null);
    const store = new DrawerZoneStore();
    store.start(null);
    expect(store.add('core.keep-awake')).toBe(true);
    expect(store.add('core.keep-awake')).toBe(false);
    store.move('core.keep-awake', 0);
    expect(ids(store)).toEqual(['core.keep-awake', 'core.ledger']);
    store.setLook('core.ledger', 'full');
    expect(store.items[1]?.look).toBe('full');
    expect(store.remove('core.keep-awake')).toBe(true);
    expect(bridge.value).toEqual({ v: 1, items: [{ widget: 'core.ledger', look: 'full' }] });
    expect(bridge.writes).toHaveLength(4);
  });

  test('another device changing the field repaints this one', () => {
    const bridge = installBridge(null);
    const store = new DrawerZoneStore();
    store.start(null);
    bridge.listeners[0]?.({ v: 1, items: [{ widget: 'core.scheduled-tasks' }] });
    expect(ids(store)).toEqual(['core.scheduled-tasks']);
  });

  test('without the preference layer the change still applies locally', () => {
    const store = new DrawerZoneStore();
    store.start(null);
    store.add('core.keep-awake');
    expect(ids(store)).toEqual(['core.ledger', 'core.keep-awake']);
  });
});
