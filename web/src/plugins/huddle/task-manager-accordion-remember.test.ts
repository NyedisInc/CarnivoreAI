/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { ACCORDION_OPEN_KEY, accordionOpenKey, accordionToggle, reloadAccordion, resetAccordion } from './task-manager-status-folds.svelte';

const projects = ['project/a', 'project/b', 'project/c'];

beforeEach(() => {
  localStorage.clear();
  resetAccordion();
});

describe('accordion open project is remembered', () => {
  test('open, reload, the same project is open', () => {
    expect(accordionOpenKey(projects)).toBe('project/a');
    accordionToggle(projects, 'project/c');
    expect(accordionOpenKey(projects)).toBe('project/c');
    resetMemoryOnly();
    reloadAccordion();
    expect(accordionOpenKey(projects)).toBe('project/c');
  });

  test('restoring on load writes nothing', () => {
    localStorage.setItem(ACCORDION_OPEN_KEY, 'project/b');
    const write = vi.spyOn(Storage.prototype, 'setItem');
    reloadAccordion();
    expect(accordionOpenKey(projects)).toBe('project/b');
    expect(write).not.toHaveBeenCalled();
    write.mockRestore();
  });

  test('a remembered project that is gone falls back to the default', () => {
    localStorage.setItem(ACCORDION_OPEN_KEY, 'project/gone');
    reloadAccordion();
    expect(accordionOpenKey(projects)).toBe('project/a');
  });
});

function resetMemoryOnly(): void {
  const kept = localStorage.getItem(ACCORDION_OPEN_KEY);
  resetAccordion();
  if (kept !== null) localStorage.setItem(ACCORDION_OPEN_KEY, kept);
}
