/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { BadgeCue, CUE_MS, railKeyTarget } from './rail-keys.svelte';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test('railKeyTarget: Up/Down and Left/Right walk with wrap, Home and End jump, anything else is not ours', () => {
  const ids = ['a', 'b', 'c'];
  expect(railKeyTarget('ArrowDown', ids, 'a')).toBe('b');
  expect(railKeyTarget('ArrowRight', ids, 'c')).toBe('a');
  expect(railKeyTarget('ArrowUp', ids, 'a')).toBe('c');
  expect(railKeyTarget('ArrowLeft', ids, 'b')).toBe('a');
  expect(railKeyTarget('Home', ids, 'c')).toBe('a');
  expect(railKeyTarget('End', ids, 'a')).toBe('c');
  expect(railKeyTarget('Enter', ids, 'a')).toBeNull();
  expect(railKeyTarget('ArrowDown', [], null)).toBeNull();
  expect(railKeyTarget('ArrowDown', ids, 'gone'), 'a focus we do not know starts at the first').toBe('a');
});

test('BadgeCue: a count that grew cues its key for CUE_MS; a first reading, a shrink or a repeat does not', () => {
  const cue = new BadgeCue();
  cue.note([{ id: 'q', count: 0 }]);
  expect(cue.id).toBeNull();
  cue.note([{ id: 'q', count: 2 }]);
  expect(cue.id).toBe('q');
  vi.advanceTimersByTime(CUE_MS + 1);
  expect(cue.id).toBeNull();
  cue.note([{ id: 'q', count: 2 }]);
  expect(cue.id, 'same count: quiet').toBeNull();
  cue.note([{ id: 'q', count: 1 }]);
  expect(cue.id, 'shrink: quiet').toBeNull();
  cue.note([{ id: 'q', count: 3 }]);
  expect(cue.id).toBe('q');
  cue.note([]);
  cue.note([{ id: 'q', count: 1 }]);
  expect(cue.id, 'a key that left and came back starts from zero').toBe('q');
});
