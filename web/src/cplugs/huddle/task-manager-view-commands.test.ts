/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test, vi } from 'vitest';

const calls = vi.hoisted(() => ({ groups: [] as { ids: number[]; folded: boolean }[] }));

vi.mock('./task-manager-groups.svelte', () => ({
  groupsOf: (list: string) => (list === '12' ? [{ id: 4, list: '12', name: 'ui', position: 1, folded: false }, { id: 5, list: '12', name: 'api', position: 2, folded: false }] : []),
  setGroupsFolded: async (groups: { id: number }[], folded: boolean) => { calls.groups.push({ ids: groups.map((g) => g.id), folded }); return true; },
}));

import { huddle } from './huddle.svelte';
import { isFolded } from './task-manager-status-folds.svelte';
import { projectFoldKey, sectionFoldKey } from './task-manager-status-folds.svelte';
import { taskManagerView } from './task-manager-view-commands';

beforeEach(() => {
  calls.groups = [];
  huddle.openId = null;
  huddle.lists = [{ key: '12', name: 'carnivore' } as never];
});

describe('task manager view commands', () => {
  test('fold on a project folds its bar, its status sections and its groups; unfold opens them again', async () => {
    await taskManagerView.fold({ action: 'fold', items: [], groups: [], project: '12' });
    expect(isFolded(projectFoldKey('12'))).toBe(true);
    expect(isFolded(sectionFoldKey('12', 'open'))).toBe(true);
    expect(calls.groups).toEqual([{ ids: [4, 5], folded: true }]);
    await taskManagerView.fold({ action: 'unfold', items: [], groups: [], project: '12' });
    expect(isFolded(projectFoldKey('12'))).toBe(false);
    expect(isFolded(sectionFoldKey('12', 'open'))).toBe(false);
    expect(calls.groups.at(-1)).toEqual({ ids: [4, 5], folded: false });
  });

  test('fold on named groups folds only those', async () => {
    await taskManagerView.fold({ action: 'fold', items: [], groups: [5], project: null });
    expect(calls.groups).toEqual([{ ids: [5], folded: true }]);
  });

  test('close collapses the opened card, and only the named one when ids are given', async () => {
    huddle.openId = 7;
    await taskManagerView.fold({ action: 'close', items: [8], groups: [], project: null });
    expect(huddle.openId).toBe(7);
    await taskManagerView.fold({ action: 'close', items: [], groups: [], project: null });
    expect(huddle.openId).toBeNull();
  });

  test('scroll to the top moves every task list box', async () => {
    document.body.innerHTML = '<div data-task-manager-scroll></div><div data-task-manager-scroll></div>';
    const boxes = [...document.querySelectorAll<HTMLElement>('[data-task-manager-scroll]')];
    boxes.forEach((b) => { b.scrollTop = 300; });
    huddle.selected = 'all';
    await taskManagerView.scrollTop(null);
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(boxes.map((b) => b.scrollTop)).toEqual([0, 0]);
  });
});
