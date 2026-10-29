import { afterEach, expect, test } from 'vitest';
import { readFootBarItems, saveFootBarItems, followFootBarItems } from './foot-bar-items';
import { footBarItems } from '../../../lib/settings-page/foot-bar-items-store.svelte';
import { DEFAULT_FOOT_BAR_ITEMS, FOOT_BAR_ITEMS_FIELD } from './foot-plan';

type G = { PreferenceBridge?: unknown };

afterEach(() => {
  delete (globalThis as G).PreferenceBridge;
});

function install(answer: unknown = { status: 'committed' }) {
  const state = { stored: undefined as unknown, writes: [] as unknown[], follow: null as null | ((v: unknown) => void) };
  (globalThis as G).PreferenceBridge = {
    read: (field: string, local: () => unknown) => {
      expect(field).toBe(FOOT_BAR_ITEMS_FIELD);
      return state.stored !== undefined ? state.stored : local();
    },
    write: async (field: string, value: unknown) => {
      expect(field).toBe(FOOT_BAR_ITEMS_FIELD);
      state.writes.push(value);
      const ok = (answer as { status: string }).status === 'committed';
      if (ok) state.stored = value;
      return answer;
    },
    follow: (field: string, apply: (v: unknown) => void) => {
      expect(field).toBe(FOOT_BAR_ITEMS_FIELD);
      state.follow = apply;
      return () => { state.follow = null; };
    },
  };
  return state;
}

test('with no bridge on the page, every item reads as shown', () => {
  expect(readFootBarItems()).toEqual(DEFAULT_FOOT_BAR_ITEMS);
});

test('with nothing stored, every item still reads as shown', () => {
  install();
  expect(readFootBarItems()).toEqual(DEFAULT_FOOT_BAR_ITEMS);
});

test('a stored partial record fills every missing id as shown', () => {
  const state = install();
  state.stored = { agents: false };
  expect(readFootBarItems()).toEqual({ ...DEFAULT_FOOT_BAR_ITEMS, agents: false });
});

test('save writes the whole record once and answers null on success', async () => {
  const state = install();
  const next = { ...DEFAULT_FOOT_BAR_ITEMS, shells: false };
  const err = await saveFootBarItems(next);
  expect(err).toBeNull();
  expect(state.writes).toEqual([next]);
});

test('a refused save reports why, and never updates what a later read returns', async () => {
  install({ status: 'refused', detail: 'not read yet' });
  const err = await saveFootBarItems({ ...DEFAULT_FOOT_BAR_ITEMS, timers: false });
  expect(err).toBe('not read yet');
});

test('with no bridge, save answers unavailable', async () => {
  expect(await saveFootBarItems(DEFAULT_FOOT_BAR_ITEMS)).toBe('unavailable');
});

test('a change on another device is normalised the same way as a read', async () => {
  const state = install();
  let seen: unknown = null;
  const stop = followFootBarItems((items) => { seen = items; });
  state.follow?.({ model: false });
  expect(seen).toEqual({ ...DEFAULT_FOOT_BAR_ITEMS, model: false });
  stop();
  expect(state.follow).toBeNull();
});

test('with no bridge, follow is a harmless no-op', () => {
  const stop = followFootBarItems(() => { throw new Error('must never be called'); });
  expect(() => stop()).not.toThrow();
});

test('absent items: agents and shells hidden, the other six shown; the settings store agrees', () => {
  install();
  expect(readFootBarItems()).toEqual({
    model: true, effort: true, context: true, window_5h: true, window_7d: true,
    agents: false, shells: false, timers: true,
  });
  footBarItems.value = {};
  expect(footBarItems.effective('shells')).toBe(false);
  expect(footBarItems.effective('agents')).toBe(false);
  expect(footBarItems.effective('timers')).toBe(true);
});

test('a stored true for agents shows it; a stored false still hides', () => {
  const state = install();
  state.stored = { agents: true, timers: false };
  expect(readFootBarItems()).toMatchObject({ agents: true, shells: false, timers: false });
  footBarItems.value = { agents: true };
  expect(footBarItems.effective('agents')).toBe(true);
});
