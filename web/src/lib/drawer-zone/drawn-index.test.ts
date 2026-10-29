/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { fullIndex } from './drawn-index';
import { DrawerZoneStore } from './zone-store.svelte';

describe('fullIndex', () => {
  const drawn = (x: string): boolean => x !== 'hidden';
  test.each([
    [0, 0],
    [1, 2],
    [2, 3],
    [9, 3],
  ])('over [a, hidden, b] a drawn index %i lands at %i', (at, want) => {
    expect(fullIndex(['a', 'hidden', 'b'], drawn, at)).toBe(want);
  });
  test('nothing drawn clamps to the list', () => {
    expect(fullIndex(['hidden'], drawn, 5)).toBe(1);
  });
});

afterEach(() => delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge);

function storeOf(widgets: string[]): DrawerZoneStore {
  const bridge = {
    read: () => ({ items: widgets.map((widget) => ({ widget })) }),
    write: async () => ({ status: 'committed' }),
    follow: () => () => {},
  };
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = bridge;
  const store = new DrawerZoneStore();
  store.start(null);
  return store;
}

describe('DrawerZoneStore with a stored widget this build cannot draw', () => {
  const ids = (s: DrawerZoneStore): string[] => s.items.map((i) => i.widget);

  test('a step down moves past the next DRAWN card, not onto the hidden one', () => {
    const store = storeOf(['core.ledger', 'ghost.nothing', 'core.themes']);
    store.step('core.ledger', 1);
    expect(ids(store)).toEqual(['ghost.nothing', 'core.themes', 'core.ledger']);
  });

  test('a drop between the two drawn cards lands between them, hidden neighbors left where they were', () => {
    const store = storeOf(['core.ledger', 'ghost.nothing', 'core.themes', 'core.projects']);
    store.move('core.projects', 1);
    expect(ids(store)).toEqual(['core.ledger', 'ghost.nothing', 'core.projects', 'core.themes']);
  });
});
