import { afterEach, expect, test } from 'vitest';
import { asFootBarLayout, readFootBarLayout, saveFootBarLayout, followFootBarLayout, DEFAULT_FOOT_BAR_LAYOUT, FOOT_BAR_LAYOUT_FIELD } from './foot-bar-layout';

type G = { PreferenceBridge?: unknown };

afterEach(() => {
  delete (globalThis as G).PreferenceBridge;
});

function install(answer: unknown = { status: 'committed' }) {
  const state = { stored: undefined as unknown, writes: [] as unknown[], follow: null as null | ((v: unknown) => void) };
  (globalThis as G).PreferenceBridge = {
    read: (field: string, local: () => unknown) => {
      expect(field).toBe(FOOT_BAR_LAYOUT_FIELD);
      return state.stored !== undefined ? state.stored : local();
    },
    write: async (field: string, value: unknown) => {
      expect(field).toBe(FOOT_BAR_LAYOUT_FIELD);
      state.writes.push(value);
      const ok = (answer as { status: string }).status === 'committed';
      if (ok) state.stored = value;
      return answer;
    },
    follow: (field: string, apply: (v: unknown) => void) => {
      expect(field).toBe(FOOT_BAR_LAYOUT_FIELD);
      state.follow = apply;
      return () => { state.follow = null; };
    },
  };
  return state;
}

test('with no bridge on the page, both halves read as the built default (a)', () => {
  expect(readFootBarLayout()).toEqual(DEFAULT_FOOT_BAR_LAYOUT);
});

test('an unknown or missing option resolves to the default, per half', () => {
  expect(asFootBarLayout({ collapsed: 'b' })).toEqual({ collapsed: 'b', open: 'a' });
  expect(asFootBarLayout({ collapsed: 'z', open: 'c' })).toEqual({ collapsed: 'a', open: 'c' });
  expect(asFootBarLayout(null)).toEqual(DEFAULT_FOOT_BAR_LAYOUT);
  expect(asFootBarLayout('nonsense')).toEqual(DEFAULT_FOOT_BAR_LAYOUT);
});

test('save writes the whole pair once and answers null on success', async () => {
  const state = install();
  const next = { collapsed: 'b' as const, open: 'c' as const };
  const err = await saveFootBarLayout(next);
  expect(err).toBeNull();
  expect(state.writes).toEqual([next]);
  expect(readFootBarLayout()).toEqual(next);
});

test('a refused save reports why', async () => {
  install({ status: 'refused', detail: 'not read yet' });
  expect(await saveFootBarLayout({ collapsed: 'c', open: 'b' })).toBe('not read yet');
});

test('with no bridge, save answers unavailable', async () => {
  expect(await saveFootBarLayout(DEFAULT_FOOT_BAR_LAYOUT)).toBe('unavailable');
});

test('a change on another device is normalised the same way as a read', () => {
  const state = install();
  let seen: unknown = null;
  const stop = followFootBarLayout((layout) => { seen = layout; });
  state.follow?.({ collapsed: 'c' });
  expect(seen).toEqual({ collapsed: 'c', open: 'a' });
  stop();
  expect(state.follow).toBeNull();
});

test('with no bridge, follow is a harmless no-op', () => {
  const stop = followFootBarLayout(() => { throw new Error('must never be called'); });
  expect(() => stop()).not.toThrow();
});
