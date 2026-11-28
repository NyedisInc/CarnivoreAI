/** @vitest-environment jsdom */
import { beforeEach, expect, test, vi } from 'vitest';
import { adoptRetiredState, bindState, resetAdoptedWidgets } from './widget-state.svelte';

const MK2 = 'core.task-manager-mk2';

beforeEach(() => localStorage.clear());

test('the retired widget\'s keys are copied under the successor, and the old keys stay', () => {
  localStorage.setItem('carnivore.core.task-manager.view', 'tree');
  localStorage.setItem('carnivore.core.task-manager.folds', '["a"]');
  expect(adoptRetiredState(MK2)).toBe(2);
  expect(localStorage.getItem(`carnivore.${MK2}.view`)).toBe('tree');
  expect(localStorage.getItem(`carnivore.${MK2}.folds`)).toBe('["a"]');
  expect(localStorage.getItem('carnivore.core.task-manager.view')).toBe('tree');
});

test('an existing successor key is never overwritten, and a second run copies nothing', () => {
  localStorage.setItem('carnivore.core.task-manager.view', 'tree');
  localStorage.setItem(`carnivore.${MK2}.view`, 'flat');
  expect(adoptRetiredState(MK2)).toBe(0);
  expect(localStorage.getItem(`carnivore.${MK2}.view`)).toBe('flat');
  localStorage.setItem('carnivore.core.task-list.mode', 'x');
  expect(adoptRetiredState(MK2)).toBe(1);
  expect(adoptRetiredState(MK2)).toBe(0);
});

test('a widget nothing retired into copies nothing', () => {
  localStorage.setItem('carnivore.core.task-manager.view', 'tree');
  expect(adoptRetiredState('core.notes')).toBe(0);
});

test('the newest naming wins: task-manager keys beat the older huddle keys, whatever the order', () => {
  localStorage.setItem('carnivore.core.huddle.view', 'old');
  localStorage.setItem('carnivore.core.task-manager.view', 'new');
  localStorage.setItem('carnivore.core.huddle-list.only', 'kept');
  expect(adoptRetiredState(MK2)).toBe(2);
  expect(localStorage.getItem(`carnivore.${MK2}.view`)).toBe('new');
  expect(localStorage.getItem(`carnivore.${MK2}.only`)).toBe('kept');
});

test('binding scans storage once per page load, not on every bind', () => {
  resetAdoptedWidgets();
  const spy = vi.spyOn(Storage.prototype, 'key');
  const spec = { view: { home: 'device', default: 'flat', valid: (v: unknown): v is string => typeof v === 'string' } } as const;
  localStorage.setItem('carnivore.core.task-manager.view', 'tree');
  bindState(MK2, spec, () => '');
  const first = spy.mock.calls.length;
  bindState(MK2, spec, () => '');
  expect(first).toBeGreaterThan(0);
  expect(spy.mock.calls.length).toBe(first);
  spy.mockRestore();
});
