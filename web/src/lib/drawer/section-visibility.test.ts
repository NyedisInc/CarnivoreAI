/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import { setDrawerController } from './controller-ref';
import { init, preferenceField, sectionShown, setSectionShown } from './section-visibility.svelte';

/** A preference bridge over a plain object; records every write. */
function bridge(store: Record<string, unknown>, writes: Array<[string, unknown]>) {
  return {
    PreferenceBridge: {
      read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
      write: vi.fn(async (field: string, value: unknown, local: () => void) => { writes.push([field, value]); store[field] = value; local(); }),
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setDrawerEnv(null);
  setViewClassSource(() => 'desktop');
  init();
});

afterEach(() => {
  setViewClassSource(null);
  setDrawerEnv(null);
  setDrawerController(null);
  vi.restoreAllMocks();
});

test('both filters are on by default and nothing is written to read that', () => {
  const writes: Array<[string, unknown]> = [];
  setDrawerEnv(bridge({}, writes));
  init();
  expect(sectionShown('open')).toBe(true);
  expect(sectionShown('sleeping')).toBe(true);
  expect(writes).toEqual([]);
});

test('the field names are the documented ones', () => {
  expect(preferenceField('open', 'desktop')).toBe('sidebar_list_open');
  expect(preferenceField('open', 'mobile')).toBe('sidebar_list_open_mobile');
  expect(preferenceField('sleeping', 'desktop')).toBe('sidebar_list_sleeping');
  expect(preferenceField('sleeping', 'mobile')).toBe('sidebar_list_sleeping_mobile');
});

test('a toggle writes its own field, refetches the list once, and the other filter is untouched', () => {
  const writes: Array<[string, unknown]> = [];
  const refreshNow = vi.fn();
  setDrawerController({ refreshNow } as never);
  setDrawerEnv(bridge({}, writes));
  expect(setSectionShown('open', false)).toBe(true);
  expect(setSectionShown('open', false), 'an unchanged answer is not a change').toBe(false);
  expect(sectionShown('open')).toBe(false);
  expect(sectionShown('sleeping')).toBe(true);
  expect(writes).toEqual([['sidebar_list_open', false]]);
  expect(refreshNow).toHaveBeenCalledTimes(1);
});

test('the phone inherits the desktop until it chooses, then keeps its own; crossing the line writes nothing', () => {
  const writes: Array<[string, unknown]> = [];
  setDrawerEnv(bridge({}, writes));
  init();
  setSectionShown('sleeping', false);
  setViewClassSource(() => 'mobile');
  init();
  expect(sectionShown('sleeping'), 'inherited').toBe(false);
  setSectionShown('sleeping', true);
  expect(writes).toEqual([['sidebar_list_sleeping', false], ['sidebar_list_sleeping_mobile', true]]);
  setViewClassSource(() => 'desktop');
  init();
  expect(sectionShown('sleeping')).toBe(false);
  setViewClassSource(() => 'mobile');
  init();
  expect(sectionShown('sleeping')).toBe(true);
  expect(writes.length, 'crossing the line wrote nothing').toBe(2);
});

test('an old section value under sidebar_show_open is never read as the filter', () => {
  setDrawerEnv(bridge({ sidebar_show_open: false, sidebar_show_sleeping: false }, []));
  init();
  expect(sectionShown('open')).toBe(true);
  expect(sectionShown('sleeping')).toBe(true);
});

test('without the bridge the choice round-trips through this browser\'s own copy', () => {
  setSectionShown('open', false);
  expect(localStorage.getItem('carnivore.session.sidebar.list_open')).toBe('0');
  setSectionShown('open', true);
  setSectionShown('open', false);
  init();
  expect(sectionShown('open')).toBe(false);
});
